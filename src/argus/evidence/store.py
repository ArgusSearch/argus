"""Agent dispatch and verification against a trusted run snapshot."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from threading import RLock
from typing import Any

import duckdb
from pydantic import BaseModel

from argus.agent.types import (
    Availability,
    ClaimDraft,
    FactHandle,
    Observation,
    ReceiptLink,
    Rejection,
    RunContext,
    RunKind,
    ToolSpec,
    VerifiedClaim,
)
from argus.contracts.findings import Anomaly, EvidenceRef, Incident, Receipt
from argus.contracts.graph import Graph
from argus.contracts.tools import TOOL_MODELS, TOOLS, HoldoutCheckInput, HoldoutCheckOutput, ListEventsOutput
from argus.counterfactual.models import CounterfactualResult, WorldConfig
from argus.counterfactual.replay import ReplayUnavailable, counterfactual
from argus.evidence.facts import Fact, has_comparison, market_facts, replay_facts, tool_facts
from argus.evidence.queries import CaptureRunner, ProofMismatch, ProofRunner, Query
from argus.evidence.validation import (
    EXTENSION_MODELS,
    ControlInput,
    CounterfactualInput,
    c6_input,
    c6_names,
    utc_window,
)
from argus.investigate.ledger import outcome_of
from argus.investigate.tools import StageTwoToolbox
from argus.market.control import check_control_group
from argus.semantic.runner import Runner

_LOG = logging.getLogger(__name__)
_C6_KINDS: dict[str, list[RunKind]] = {
    "get_series": ["investigate", "ask", "verify_effect"],
    "check_freshness": ["investigate", "ask", "verify_effect"],
    "check_identities": ["investigate"],
    "decompose_formula": ["investigate", "ask"],
    "mix_rate_split": ["investigate", "ask"],
    "segment_search": ["investigate", "ask"],
    "list_events": ["investigate", "ask"],
    "holdout_check": ["investigate", "ask"],
    "placebo_test": ["investigate", "ask"],
    "counterfactual_impact": ["investigate", "ask"],
}
_EXTENSIONS: dict[str, tuple[str, list[RunKind]]] = {
    "check_control_group": ("Compare the visible anomaly with market demand.", ["investigate", "ask"]),
    "counterfactual": ("Replay a supported fault in a paired simulator world.", ["ask", "verify_effect"]),
}


@dataclass
class _Result:
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    events: list[EvidenceRef] = field(default_factory=list)
    outcome: str | None = None
    unavailable: bool = False


@dataclass(frozen=True)
class _Paired:
    incident: Incident
    config: WorldConfig
    reference: Receipt
    result: CounterfactualResult
    proofs: tuple[Receipt, Receipt]


@dataclass(frozen=True)
class _Call:
    name: str
    args: BaseModel
    queries: tuple[Query, ...]
    facts: tuple[Fact, ...]
    refs: tuple[ReceiptLink, ...]
    event_query: Query | None = None
    paired: _Paired | None = None


@dataclass
class _Session:
    ctx: RunContext
    graph: Graph
    runner: Runner
    latest_hour: datetime
    anomaly: Anomaly | None
    incidents: dict[str, Incident]
    config: WorldConfig | None
    events: dict[tuple[str, str], EvidenceRef]
    event_queries: dict[tuple[str, str], Query] = field(default_factory=dict)
    queries: dict[str, Query] = field(default_factory=dict)
    paired: dict[str, _Paired] = field(default_factory=dict)
    facts: dict[str, tuple[_Call, int]] = field(default_factory=dict)
    claims: dict[str, VerifiedClaim] = field(default_factory=dict)
    call_count: int = 0
    lock: RLock = field(default_factory=RLock)


class EvidenceStore:
    """One service per source. Bind the pinned read resources before dispatching a run."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str, str], _Session] = {}
        self._lock = RLock()

    def bind(
        self,
        ctx: RunContext,
        *,
        graph: Graph,
        runner: Runner,
        latest_hour: datetime,
        anomaly: Anomaly | None = None,
        events: Sequence[EvidenceRef] = (),
        incidents: Sequence[Incident] = (),
        config: WorldConfig | None = None,
    ) -> None:
        """Register only data already visible in the caller's selected C5 prefix."""
        if (
            ctx.as_of.tzinfo is not None
            or latest_hour.tzinfo is not None
            or latest_hour != latest_hour.replace(minute=0, second=0, microsecond=0)
            or latest_hour > ctx.as_of
            or (anomaly is not None and (anomaly.id != ctx.anomaly_id or anomaly.detected_at > ctx.as_of))
        ):
            raise ValueError("Invalid clock or anomaly for the evidence run.")
        session = _Session(
            ctx.model_copy(deep=True),
            graph.model_copy(deep=True),
            runner,
            latest_hour,
            anomaly.model_copy(deep=True) if anomaly else None,
            {
                incident.id: incident.model_copy(deep=True)
                for incident in incidents
                if incident.findings.as_of <= ctx.as_of and incident.updated_at <= ctx.as_of
            },
            config,
            {(event.log, event.ref): event.model_copy(deep=True) for event in events if event.ts <= ctx.as_of},
        )
        key = (ctx.stream, ctx.run_id, ctx.world_revision)
        with self._lock:
            if key in self._sessions:
                raise ValueError("Evidence is already bound for this run.")
            self._sessions[key] = session

    def _session(self, ctx: RunContext) -> _Session | None:
        with self._lock:
            session = self._sessions.get((ctx.stream, ctx.run_id, ctx.world_revision))
        return session if session is not None and session.ctx == ctx else None

    def context_for(self, stream: str, ref: ReceiptLink, *, through_seq: int, as_of: datetime) -> RunContext | None:
        """Resolve a qualified link against the active stream's visible prefix and clock."""
        with self._lock:
            session = self._sessions.get((stream, ref.run_id, ref.world_revision))
        if session and session.ctx.through_seq <= through_seq and session.ctx.as_of <= as_of:
            return session.ctx.model_copy(deep=True)
        return None

    @staticmethod
    def specs(kind: RunKind) -> list[ToolSpec]:
        """Provider catalogue built from the Stage 2 handlers and frozen C6 input schemas."""
        descriptions = {spec.name: spec.description for spec in TOOLS}
        return [
            ToolSpec(
                name=name,
                description=descriptions[name],
                input_schema=TOOL_MODELS[name][0].model_json_schema(),
                kinds=_C6_KINDS[name],
            )
            for name in c6_names()
            if kind in _C6_KINDS[name]
        ]

    @staticmethod
    def _ref(ctx: RunContext, rid: str) -> ReceiptLink:
        return ReceiptLink(run_id=ctx.run_id, world_revision=ctx.world_revision, receipt_id=rid)

    def dispatch(self, ctx: RunContext, name: str, args: dict[str, Any]) -> Observation:
        session = self._session(ctx)
        if session is None:
            return Observation(
                call_id=f"{ctx.run_id}:0",
                tool=name,
                args={},
                availability="rejected",
                summary="Evidence is unavailable for this run.",
            )
        with session.lock:
            session.call_count += 1
            call_id = f"{ctx.run_id}:{session.call_count}"

            def reject(status: Availability, summary: str) -> Observation:
                return Observation(call_id=call_id, tool=name, args={}, availability=status, summary=summary)

            try:
                if name in c6_names() and ctx.kind in _C6_KINDS[name]:
                    data = c6_input(
                        name,
                        args,
                        graph=session.graph,
                        as_of=ctx.as_of,
                        latest_hour=session.latest_hour,
                        events=session.events,
                    )
                elif name in _EXTENSIONS and ctx.kind in _EXTENSIONS[name][1]:
                    data = EXTENSION_MODELS[name].model_validate(args)
                else:
                    return reject("rejected", "This tool is unavailable for the run.")
            except (KeyError, TypeError, ValueError):
                return reject("rejected", "Use the tool schema and choose visible metrics, segments and times.")

            capture = CaptureRunner(session.runner)
            paired = None
            try:
                if isinstance(data, CounterfactualInput):
                    result, paired = _run_counterfactual(session, data.incident_id)
                else:
                    result = _run(session, capture, name, data)
            except ReplayUnavailable:
                result = _Result("No matching counterfactual replay is available.", unavailable=True)
            except (duckdb.Error, OSError, RuntimeError, TypeError, ValueError, IndexError, KeyError, OverflowError):
                _LOG.warning("Evidence tool %s failed", name)
                return reject("error", "The tool could not complete its reads.")

            queries = tuple(capture.queries)
            receipts = tuple(query.receipt for query in queries) if paired is None else paired.proofs
            event_query = (
                session.event_queries.get((data.event.log, data.event.ref))
                if isinstance(data, HoldoutCheckInput)
                else None
            )
            if event_query is not None:
                receipts += (event_query.receipt,)
            refs = tuple(self._ref(ctx, receipt.id) for receipt in receipts)
            facts = tuple(fact for fact in result.facts if refs and isfinite(fact.value))
            binding = _Call(name, data.model_copy(deep=True), queries, facts, refs, event_query, paired)
            handles = []
            for index, fact in enumerate(facts):
                fid = f"f:{ctx.run_id}:{call_id}:{index + 1}"
                session.facts[fid] = (binding, index)
                handles.append(
                    FactHandle(
                        id=fid,
                        label=fact.coordinate(),
                        value=fact.value,
                        unit=fact.unit,
                        receipts=[ref.model_copy(deep=True) for ref in refs],
                    )
                )

            session.queries.update((query.receipt.id, query) for query in queries)
            if paired:
                session.paired.update((receipt.id, paired) for receipt in paired.proofs)
            session.events.update(((event.log, event.ref), event.model_copy(deep=True)) for event in result.events)
            if result.events:
                session.event_queries.update(((event.log, event.ref), queries[0]) for event in result.events)
            return Observation(
                call_id=call_id,
                tool=name,
                args=data.model_dump(mode="json"),
                outcome=result.outcome,
                summary=result.summary,
                data=result.data,
                fact_handles=handles,
                receipt_refs=[ref.model_copy(deep=True) for ref in refs],
                availability="unavailable" if result.unavailable else "ok",
            )

    def inspect_receipt(self, ctx: RunContext, ref: ReceiptLink) -> Receipt | None:
        session = self._session(ctx)
        if session is None or ref != self._ref(ctx, ref.receipt_id):
            return None
        with session.lock:
            if query := session.queries.get(ref.receipt_id):
                return query.receipt.model_copy(deep=True)
            if paired := session.paired.get(ref.receipt_id):
                return next(receipt.model_copy(deep=True) for receipt in paired.proofs if receipt.id == ref.receipt_id)
        return None

    def rerun_receipt(self, ctx: RunContext, ref: ReceiptLink) -> tuple[str, bool] | None:
        """Return the pinned hash and whether the bound query still reproduces its rows."""
        session = self._session(ctx)
        if session is None or (receipt := self.inspect_receipt(ctx, ref)) is None:
            return None
        with session.lock:
            try:
                if query := session.queries.get(ref.receipt_id):
                    query.read(session.runner)
                else:
                    _rerun_paired(session, session.paired[ref.receipt_id])
            except (ProofMismatch, ReplayUnavailable, duckdb.Error, OSError):
                return receipt.result_hash, False
        return receipt.result_hash, True

    def receipt_rows(self, ctx: RunContext, ref: ReceiptLink, *, limit: int = 20) -> list[dict[str, Any]] | None:
        """Return a bounded sample after verifying the entire bound read."""
        session = self._session(ctx)
        if session is None or ref != self._ref(ctx, ref.receipt_id):
            return None
        if not 0 <= limit <= 100:
            raise ValueError("Sample at most 100 rows.")
        with session.lock:
            query = session.queries.get(ref.receipt_id)
            if query is None:
                return None
            try:
                return query.read(session.runner)[:limit]
            except (ProofMismatch, duckdb.Error, OSError):
                return None

    def verify(self, ctx: RunContext, draft: ClaimDraft) -> VerifiedClaim | Rejection:
        session = self._session(ctx)
        if session is None:
            return Rejection(reason="stale", detail="The run's clock, revision or visible prefix differs.")
        if re.search(r"\d", draft.text):
            return Rejection(reason="unbacked_number", detail="Supply fact handles and leave figures to the renderer.")
        if not draft.fact_ids:
            return Rejection(reason="missing_check", detail="The claim needs a fact from a receipted check.")
        if len(draft.fact_ids) != 1:
            return Rejection(reason="invalid", detail="Submit one independently bound fact per claim.")
        try:
            window = utc_window(draft.window) if draft.window else None
        except ValueError:
            return Rejection(reason="stale", detail="Use a UTC time interval.")
        fid = draft.fact_ids[0]
        with session.lock:
            entry = session.facts.get(fid)
            if entry is None:
                return Rejection(reason="unknown_fact", detail="The fact is outside this run.")
            call, index = entry
            fact = call.facts[index]
            if (fact.subject, fact.segment) != (draft.subject, draft.segment):
                return Rejection(reason="wrong_subject", detail="The fact describes a different metric or segment.")
            if window != fact.window:
                return Rejection(reason="stale", detail="The fact describes a different time interval.")
            if draft.kind != fact.kind:
                return Rejection(reason="wrong_unit", detail="The fact measures a different quantity.")
            if not _reproduces(session, call):
                return Rejection(reason="stale", detail="The bound query rows or the selected field did not reproduce.")
            claim = VerifiedClaim(
                claim_id=f"c:{fid.removeprefix('f:')}",
                kind=fact.kind,
                subject=fact.subject,
                segment=fact.segment,
                window=fact.window,
                as_of=ctx.as_of,
                world_revision=ctx.world_revision,
                value=fact.value,
                unit=fact.unit,
                display=f"{fact.render()} " + " ".join(f"[{ref.receipt_id}]" for ref in call.refs) + ".",
                receipts=list(call.refs),
            )
            session.claims.setdefault(fid, claim.model_copy(deep=True))
            return claim.model_copy(deep=True)

    def verified_claims(self, ctx: RunContext) -> tuple[VerifiedClaim, ...]:
        session = self._session(ctx)
        if session is None:
            return ()
        with session.lock:
            return tuple(claim.model_copy(deep=True) for claim in session.claims.values())

    def claims_at(self, stream: str, through_seq: int, as_of: datetime) -> list[tuple[RunContext, VerifiedClaim]]:
        """Read the verified claim journal through a visible stream prefix."""
        with self._lock:
            contexts = [
                session.ctx
                for session in self._sessions.values()
                if session.ctx.stream == stream
                and session.ctx.through_seq <= through_seq
                and session.ctx.as_of <= as_of
            ]
        return [(ctx.model_copy(deep=True), claim) for ctx in contexts for claim in self.verified_claims(ctx)]


def _run(session: _Session, runner: CaptureRunner | ProofRunner, name: str, args: BaseModel) -> _Result:
    if isinstance(args, ControlInput):
        anomaly = session.anomaly
        if anomaly is None or args.anomaly_id != anomaly.id or anomaly.hour > session.latest_hour:
            return _Result("The anomaly is unavailable in this run.", unavailable=True)
        market = check_control_group(runner, session.graph, anomaly, session.ctx.as_of)
        if market is None:
            return _Result("No matching market control is available.", unavailable=True)
        return _Result(
            market.reason,
            market.model_dump(mode="json", exclude={"receipt_id"}),
            market_facts(market, session.graph),
            outcome=market.verdict,
        )

    output = StageTwoToolbox(session.graph, runner, session.ctx.as_of).run(name, args.model_dump())
    data = output.model_dump(mode="json", exclude={"summary", "receipts"})
    if isinstance(output, HoldoutCheckOutput):
        data["holdout"].pop("where", None)
    if not output.receipts:
        return _Result("This check has no applicable query evidence.", unavailable=True)

    declared = [runner.rows[rid] for rid in output.receipts]
    missing_comparison = (
        name in {"counterfactual_impact", "segment_search", "mix_rate_split"} and not has_comparison(declared[0])
    ) or (
        name == "holdout_check" and not all(has_comparison(rows, needs_relative=True) for rows in runner.rows.values())
    )
    missing_identity = name == "check_identities" and any(
        value is None for rows in declared for row in rows for key, value in row.items() if key.startswith("cur_")
    )
    unavailable = (
        missing_comparison
        or missing_identity
        or (name == "placebo_test" and data["weeks"] == 0)
        or (name == "decompose_formula" and not _has_formula_inputs(session.graph, data["factors"], declared))
        or (name == "get_series" and all(point["value"] is None for point in data["points"]))
        or (isinstance(output, HoldoutCheckOutput) and output.result == "not_applicable")
    )
    if unavailable:
        return _Result("The check lacks comparable data or does not apply to this scope.", unavailable=True)

    if name == "counterfactual_impact" and not any(
        row.get("base_orders") and row.get("base_gmv") is not None for rows in declared for row in rows
    ):
        data["gmv_eur_per_hour"] = None
    facts = tool_facts(name, data, args, session.graph, runner.rows)
    if name == "list_events":
        data["events"] = data["events"][:24]
    result = outcome_of(name, output)
    summary = f"{name.replace('_', ' ').capitalize()}: {result or 'observed'}."
    return _Result(
        summary,
        data,
        facts,
        events=output.events[:24] if isinstance(output, ListEventsOutput) else [],
        outcome=result,
    )


def _has_formula_inputs(graph: Graph, factors: list[str], reads: list[list[dict[str, Any]]]) -> bool:
    denominators = {
        graph.node(denominator).measure for factor in factors if (denominator := graph.node(factor).denominator)
    }
    return bool(factors) and all(
        value is not None and (value != 0 or key.split("_", 1)[-1] not in denominators)
        for rows in reads
        for row in rows
        for key, value in row.items()
    )


def _run_counterfactual(session: _Session, incident_id: str) -> tuple[_Result, _Paired]:
    incident = session.incidents.get(incident_id)
    if incident is None or session.config is None:
        raise ReplayUnavailable("The incident or the paired replay configuration is unavailable.")
    root = incident.findings.root
    rid = root.change_pct.receipt if root else None
    reference = session.runner.receipts.get(rid) if rid else None
    if reference is None or reference.as_of > session.ctx.as_of:
        raise ReplayUnavailable("The incident's factual receipt is unavailable.")
    result = counterfactual(incident, config=session.config, as_of=session.ctx.as_of, reference=reference)
    proofs = tuple(
        Receipt(
            id=f"cf-{session.call_count}-{side}",
            sql=proof.sql,
            rows=proof.rows,
            result_hash=proof.result_hash,
            as_of=result.receipt.plan.as_of,
            ms=0,
            purpose=f"Paired simulator replay: {side} world",
        )
        for side, proof in (("factual", result.receipt.factual), ("counterfactual", result.receipt.counterfactual))
    )
    paired = _Paired(incident, session.config, reference.model_copy(deep=True), result, (proofs[0], proofs[1]))
    data = result.model_dump(mode="json", include={"explained_share", "gap"})
    facts = replay_facts(result, session.graph)
    return _Result("Compared the factual and cause-off simulator worlds.", data, facts), paired


def _rerun_paired(session: _Session, paired: _Paired) -> CounterfactualResult:
    if session.runner.receipts.get(paired.reference.id) != paired.reference:
        raise ProofMismatch("The incident's factual reference changed.")
    result = counterfactual(paired.incident, config=paired.config, as_of=session.ctx.as_of, reference=paired.reference)
    if result != paired.result:
        raise ProofMismatch("The paired replay no longer reproduces its original evidence.")
    return result


def _reproduces(session: _Session, call: _Call) -> bool:
    try:
        if call.event_query is not None:
            call.event_query.read(session.runner)
        if call.paired:
            facts = replay_facts(_rerun_paired(session, call.paired), session.graph)
        else:
            runner = ProofRunner(session.runner, call.queries)
            facts = _run(session, runner, call.name, call.args).facts
            runner.finish()
    except (ValueError, RuntimeError, duckdb.Error, OSError, IndexError, KeyError, OverflowError):
        return False
    return tuple(fact for fact in facts if isfinite(fact.value)) == call.facts
