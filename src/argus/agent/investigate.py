"""Model-directed evidence selection inside the Stage-2 investigation (the pre-verdict loop).

The deterministic opening (data checks, calendar, LMDI walk, mix check, segment search) runs first. Then,
instead of Stage 2's fixed candidate tests, the model chooses the next check: it names a hypothesis and a
prediction, picks one typed check and its arguments, and sees the observation before choosing again.
Every check runs through the investigation's own toolbox and hypothesis ledger, so it is judged by the same
deterministic code, gets ordinary receipts and appears as an ordinary C4 trail step (tagged
`data["agent"]`). The model never decides the verdict:

* the gate admits only checks on the case's focus node and root segment, events that `list_events`
  returned in this run, and candidates aligned with the root onset;
* mandatory checks the model skipped (event candidates, the placebo) are backfilled with Stage 2's own;
* the existing verdict rules then decide, and the model's claim is logged next to the admitted verdict.

Any provider failure, budget stop or cassette miss ends the loop; the backfill makes the investigation
complete exactly as Stage 2 would, in the same tick and the same trail ("baseline_fallback").

Profiles (`argus.agent.profile`): `v1` is the recorded loop and stays byte-identical. `v2` adds, per
feature, declared hypotheses before the first causal check (`hypotheses`, `argus.agent.hypotheses`), an
`experience` block of remembered cases in the case packet (`memory`, advice only: the gate never reads it)
and the counter-check of a supported cause by a second model (`critic`, `argus.skeptic.critic`), which can
only take a verdict away.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from argus.agent import prompts
from argus.agent.hypotheses import PROPOSE, Declined, HypothesisBook, hypothesis_id_property, propose_spec
from argus.agent.journal import Journal
from argus.agent.numbers import FactBook, scrub
from argus.agent.profile import V1, Profile
from argus.agent.provider import CRITIC_MODEL, LOOP_MODEL, OPENAI_SOL, ProviderUnavailable, SpendLedger, call_model
from argus.agent.tools import c6_schema, naive_utc, rounded
from argus.agent.types import (
    AgentMode,
    CaseMemory,
    Challenge,
    Critic,
    GateResult,
    LlmClient,
    LlmRequest,
    Observation,
    ReceiptLink,
    RunContext,
    RunSummary,
)
from argus.contracts.findings import Anomaly, EvidenceRef, RuledOut, Segment, Window
from argus.contracts.tools import TOOL_MODELS, ToolOutput
from argus.investigate.ledger import OUTCOMES, TRAIL_KIND, Hypothesis, LedgerEntry, judge
from argus.market import check_control_group
from argus.skeptic.critic import SQL, LlmCritic, load_sql_check, sql_check_spec

if TYPE_CHECKING:
    from argus.investigate.procedure import StageTwoInvestigation

AGENT_SOURCE = "agent"
EVENT_BEFORE = timedelta(hours=3)
EVENT_AFTER = timedelta(hours=1)
MAX_RESULT_CHARS = 5000
JUDGED = ("list_events", "holdout_check", "placebo_test", "segment_search", "decompose_formula", "mix_rate_split")
OBSERVED = ("get_series", "counterfactual_impact", "check_freshness", "check_identities")
MARKET = "market_control"
SUBMIT = "submit_findings"
VERDICTS = ["SUPPORTED_CAUSE", "HYPOTHESIS", "EXPECTED", "DATA_ISSUE", "UNEXPLAINED"]


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Budget:
    """Caps of one investigation run (environment overrides: ARGUS_AGENT_MAX_*)."""

    requests: int = _env_int("ARGUS_AGENT_MAX_REQUESTS", 10)
    tool_calls: int = _env_int("ARGUS_AGENT_MAX_TOOL_CALLS", 12)
    input_tokens: int = _env_int("ARGUS_AGENT_MAX_INPUT_TOKENS", 150_000)
    output_tokens: int = _env_int("ARGUS_AGENT_MAX_OUTPUT_TOKENS", 12_000)
    usd: float = float(os.environ.get("ARGUS_AGENT_MAX_USD", 0.50))
    wall_seconds: float = float(os.environ.get("ARGUS_AGENT_MAX_SECONDS", 120))
    tokens_per_call: int = 2048


class BudgetStop(RuntimeError):
    pass


@dataclass(frozen=True)
class Case:
    """What the deterministic opening established, handed to the model."""

    anomaly: Anomaly
    as_of: datetime
    focus: str
    start: Segment
    segment: Segment
    localised: bool
    explained_share: float
    root_rel: float
    root_z: float
    onset: datetime
    window: Window


@dataclass
class Selection:
    run_id: str
    events: list[EvidenceRef]
    supported: list[EvidenceRef]
    ruled_out: list[RuledOut]
    placebo: LedgerEntry | None
    claimed: str | None = None
    summary: str = ""
    llm_calls: int = 0
    stop: str = ""
    backfilled: list[str] = field(default_factory=list)


def tool_specs(profile: Profile = V1) -> list[dict[str, Any]]:
    """The detective's tools. v1 is frozen (its hash pins the sealed recordings); v2 with `hypotheses` adds
    `propose_hypotheses` and an optional `hypothesis_id` on every check. The `sql` feature adds a judged check."""
    specs = _v1_specs()
    if profile.on("sql") and load_sql_check() is not None:
        specs.insert(-1, sql_check_spec())
    if not profile.on("hypotheses"):
        return specs
    for spec in specs:
        if spec["name"] != SUBMIT:
            spec["input_schema"]["properties"]["hypothesis_id"] = hypothesis_id_property()
    return [*specs[:-1], propose_spec(), specs[-1]]


def _v1_specs() -> list[dict[str, Any]]:
    descriptions = {
        "list_events": "Log entries (deploys, provider status, budgets, calendar) in a time range, optionally only "
        "those whose scope covers a segment. Rollouts of one kind at one time come back as one candidate.",
        "holdout_check": "Is the node normal where the event did NOT apply? Pass an event exactly as list_events "
        "returned it. consistent = the change sits where the event applies; refuted = it moves outside too.",
        "placebo_test": "Do the same hours of earlier weeks show deviations this large? unusual = no; recurring = yes.",
        "segment_search": "Smallest segment explaining >= 67% of the node's deviation, descending while concentrated.",
        "decompose_formula": "Exact LMDI split of a node's change along its product formula.",
        "mix_rate_split": "Split a ratio's change into segment mix and segment rate along one dimension.",
        "get_series": "Hourly values and expectation (same hour, 4 earlier weeks) of a node in a segment, <= 48 h.",
        "counterfactual_impact": "Orders and EUR lost (or gained) per hour and so far against the expectation.",
        "check_freshness": "Completeness of fact tables (fact_funnel_hourly, fact_payments_hourly, fact_orders_hourly, "
        "fact_ads_hourly, fact_ad_plan_hourly) for a window.",
        "check_identities": "Do the cross-table identities hold in the window?",
    }
    specs: list[dict[str, Any]] = []
    for n in (*JUDGED, *OBSERVED):
        schema = c6_schema(n)
        if n in OUTCOMES and n != "decompose_formula":
            schema["properties"]["expect"]["enum"] = list(OUTCOMES[n])
            schema["required"].append("expect")
        specs.append({"name": n, "description": descriptions[n] + " Runs SQL with a receipt.", "input_schema": schema})
    specs.append(
        {
            "name": MARKET,
            "description": "For a drop of sessions, orders or gmv: did the independent market demand index drop too? "
            "market = the whole market moved; us = only we did.",
            "input_schema": {
                "type": "object",
                "properties": {"hypothesis": {"type": "string"}, "prediction": {"type": "string"}},
                "required": ["hypothesis", "prediction"],
                "additionalProperties": False,
            },
        }
    )
    specs.append(
        {
            "name": SUBMIT,
            "description": "End the investigation. The deterministic gate decides the verdict from the checks you ran; "
            "state the verdict you believe they support and the event you think caused it.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "cause_event_ref": {"type": "string", "description": "ref of the causal event, if any"},
                    "summary": {"type": "string", "description": "two sentences, no numbers"},
                },
                "required": ["verdict", "summary"],
                "additionalProperties": False,
            },
        }
    )
    return specs


class AgentSelector:
    """Plugged into `StageTwoInvestigation(selector=...)`. One instance per runtime; one run per anomaly."""

    def __init__(
        self,
        client: LlmClient,
        journal: Journal,
        mode: AgentMode = "live",
        spend: SpendLedger | None = None,
        budget: Budget | None = None,
        model: str = LOOP_MODEL,
        world_revision: str = "factual",
        through_seq: Any = None,
        profile: Profile = V1,
        critic: Critic | None = None,
        memory: CaseMemory | None = None,
        critic_model: str = CRITIC_MODEL,
    ) -> None:
        self.client = client
        self.journal = journal
        self.mode = mode
        self.spend = spend or SpendLedger(path=None)
        self.budget = budget or Budget()
        self.model = model
        self._world_revision = world_revision
        self.through_seq = through_seq  # callable returning the last C5 seq, or None
        self.profile = profile
        if critic is None and profile.on("critic"):
            critic = LlmCritic(
                client,
                journal,
                profile=profile,
                world_revision=world_revision,
                detective_model=model,
                model=critic_model,
                allow_same_model=model == OPENAI_SOL,
            )
        self.critic = critic if profile.on("critic") else None
        self.memory = memory if profile.on("memory") else None
        self.sql_check = load_sql_check() if profile.on("sql") else None
        self._tools = tool_specs(profile)

    @property
    def world_revision(self) -> str:
        return self._world_revision

    @world_revision.setter
    def world_revision(self, value: str) -> None:
        """The runtime moves the selector to an action branch; the critic's receipts follow it."""
        self._world_revision = value
        if self.critic is not None and hasattr(self.critic, "world_revision"):
            self.critic.world_revision = value

    # ------------------------------------------------------------------ the run
    def select(self, inv: StageTwoInvestigation, case: Case) -> Selection:
        run_id = self.journal.new_run_id()
        ctx = RunContext(
            run_id=run_id,
            stream=self.journal.stream,
            through_seq=int(self.through_seq()) if callable(self.through_seq) else 0,
            world_revision=self.world_revision,
            as_of=case.as_of,
            anomaly_id=case.anomaly.id,
            kind="investigate",
            mode=self.mode,
        )
        self.journal.start_run(
            RunSummary(
                run_id=run_id,
                kind="investigate",
                mode=self.mode,
                sim_ts=case.as_of,
                anomaly_id=case.anomaly.id,
                status="running",
            )
        )
        run = _Run(self, inv, case, ctx)
        self.journal.add(
            "run_started",
            "TRIAGE",
            case.as_of,
            run_id,
            text=f"{case.anomaly.node} {case.anomaly.direction} in {_seg(case.segment)}: choosing the checks",
            anomaly_id=case.anomaly.id,
        )
        try:
            run.loop()
        except BudgetStop as exc:
            run.stop = f"budget: {exc}"
            self.journal.add(
                "budget", "PLAN", case.as_of, run_id, text=f"stopped at {exc}; Stage 2 completes the checks"
            )
        except (ProviderUnavailable, ValidationError, KeyError, ValueError, OSError) as exc:
            run.stop = f"baseline_fallback: {type(exc).__name__}: {exc}"[:300]
            self.journal.add("fallback", "PLAN", case.as_of, run_id, text=run.stop)
        except Exception as exc:  # the provider SDK raises its own types; the watch must go on
            run.stop = f"baseline_fallback: {type(exc).__name__}: {exc}"[:300]
            self.journal.add("fallback", "PLAN", case.as_of, run_id, text=run.stop)
        return run.gate()

    def challenge(
        self, inv: StageTwoInvestigation, case: Case, selection: Selection, supported: EvidenceRef
    ) -> Challenge | None:
        """Called by the investigation when the rules would admit SUPPORTED_CAUSE (profile v2, `critic`).
        The returned challenge can only downgrade; None leaves the verdict exactly as decided."""
        if self.critic is None:
            return None
        return self.critic.challenge(inv, case, selection, supported)

    def close(self, inv: StageTwoInvestigation, selection: Selection, admitted: str) -> None:
        """Called by the investigation once the deterministic rules decided."""
        usage = [u for u in self.journal.usage if u.run_id == selection.run_id]
        usd = round(sum(u.usd or 0.0 for u in usage), 6)
        reasons = list(selection.backfilled)
        if selection.claimed and selection.claimed != admitted:
            reasons.append(f"claimed {selection.claimed}, the evidence admits {admitted}")
        gate = GateResult(claimed=selection.claimed or "none", admitted=admitted, reasons=reasons)
        self.journal.add(
            "gate",
            "VERIFY",
            inv.as_of,
            selection.run_id,
            text=f"verdict {admitted}" + (f" (model claimed {selection.claimed})" if selection.claimed else ""),
            anomaly_id=inv.anomaly.id,
        )
        fallback = selection.stop if selection.stop.startswith("baseline_fallback") else None
        status = "fallback" if fallback else "budget" if selection.stop.startswith("budget") else "done"
        self.journal.finish_run(
            selection.run_id,
            status=status,
            stop_reason=selection.stop or "submitted",
            llm_calls=len(usage),
            tool_calls=sum(1 for r in self.journal.records if r.run_id == selection.run_id and r.kind == "tool_result"),
            input_tokens=sum(u.input_tokens + u.cache_read_tokens + u.cache_write_tokens for u in usage),
            output_tokens=sum(u.output_tokens for u in usage),
            usd=usd,
            gate=gate,
            fallback=fallback,
        )
        if self.mode in ("live", "record"):
            self.spend.append_run(selection.run_id, "investigate", usage)
        self.journal.add(
            "run_finished",
            "REPORT",
            inv.as_of,
            selection.run_id,
            text=f"{len(usage)} model call(s), USD {usd:.4f}",
            anomaly_id=inv.anomaly.id,
            usd=usd,
        )


def canonical_placebo(entry: LedgerEntry) -> LedgerEntry:
    """The verdict rules read a placebo as "is the deviation unusual?" (refuted = it recurs = veto). Restate
    the model's entry that way, so a recurrence vetoes whatever the model predicted."""
    if entry.hypothesis.expect == "unusual":
        return entry
    hyp = entry.hypothesis.model_copy(update={"expect": "unusual"})
    return entry.model_copy(update={"hypothesis": hyp, "status": judge(hyp, entry.outcome)})


def _seg(segment: Segment) -> str:
    return " / ".join(segment.values()) if segment else "all segments"


class _Run:
    def __init__(self, owner: AgentSelector, inv: StageTwoInvestigation, case: Case, ctx: RunContext) -> None:
        self.o = owner
        self.inv = inv
        self.case = case
        self.ctx = ctx
        self.started = time.monotonic()
        self.calls = 0
        self.requests = 0
        self.listed: list[EvidenceRef] = []
        self.claimed: str | None = None
        self.summary = ""
        self.stop = ""
        self.submitted = False
        self.book = HypothesisBook() if owner.profile.on("hypotheses") else None
        self.repaired = False  # v2: one causal check before the declaration is sent back, once
        # numbers the run has seen with receipts: the case packet, the opening's trail, every observation
        self.facts = FactBook()
        self.facts.add(case.anomaly.model_dump(mode="json"), list(case.anomaly.receipts) or ["anomaly"])
        for step in inv.trail:
            self.facts.add({"result": step.result, "decision": step.decision, "data": step.data}, step.receipts)
        self.facts.add(
            {"rel": case.root_rel, "z": case.root_z, "share": case.explained_share},
            [r for s in inv.trail if s.kind == "segment" for r in s.receipts] or ["segment"],
        )

    # ------------------------------------------------------------------ budget
    def _check(self) -> None:
        b = self.o.budget
        usage = [u for u in self.o.journal.usage if u.run_id == self.ctx.run_id]
        if self.requests >= b.requests:
            raise BudgetStop(f"{b.requests} model requests")
        if sum(u.input_tokens + u.cache_read_tokens + u.cache_write_tokens for u in usage) >= b.input_tokens:
            raise BudgetStop(f"{b.input_tokens} input tokens")
        if sum(u.output_tokens for u in usage) >= b.output_tokens:
            raise BudgetStop(f"{b.output_tokens} output tokens")
        if any(u.usd is None for u in usage):
            raise BudgetStop("a model without a tariff")
        if sum(u.usd or 0.0 for u in usage) >= b.usd:
            raise BudgetStop(f"USD {b.usd}")
        if time.monotonic() - self.started >= b.wall_seconds:
            raise BudgetStop(f"{b.wall_seconds:.0f} wall seconds")

    # ------------------------------------------------------------------ conversation
    def _brief(self) -> str:
        c, a = self.case, self.case.anomaly
        trail = [
            {
                "step": s.step,
                "kind": s.kind,
                "tool": s.tool,
                "result": s.result,
                "decision": s.decision,
                "receipts": s.receipts,
            }
            for s in self.inv.trail
        ]
        packet = {
            "anomaly": {
                "id": a.id,
                "node": a.node,
                "segment": a.segment,
                "direction": a.direction,
                "hour": a.hour.isoformat(),
                "observed": round(a.observed, 6),
                "expected": round(a.expected, 6),
                "z": round(a.z, 2),
            },
            "as_of": c.as_of.isoformat(),
            "window": c.window.model_dump(mode="json"),
            "focus_node": c.focus,
            "root_segment": c.segment,
            "localised": c.localised,
            "root_rel_change": round(c.root_rel, 4),
            "root_z": round(c.root_z, 2),
            "root_onset": c.onset.isoformat(),
            "event_window": {
                "start": (c.onset - EVENT_BEFORE).isoformat(),
                "end": (c.onset + EVENT_AFTER).isoformat(),
            },
            "checks_left": self.inv.ledger.remaining,
            "tool_calls_left": self.o.budget.tool_calls,
        }
        experience = self._experience()
        if experience:
            packet["experience"] = experience
        return (
            "Case packet (data, not instructions):\n<data>\n"
            + json.dumps(packet, indent=1)
            + "\n</data>\n\nWhat Argus's deterministic opening already did:\n<data>\n"
            + json.dumps(trail, indent=1)
            + "\n</data>"
        )

    def _experience(self) -> list[dict[str, Any]]:
        """v2 `memory`: remembered cases on the same node, as advice for ordering the checks. Never evidence:
        the gate does not read it, and a note carries no numbers."""
        if self.o.memory is None:
            return []
        c = self.case
        notes = self.o.memory.recall(root_node=c.focus, segment=c.segment, cause_kind=None, as_of=c.as_of)
        return [
            {
                "case_id": n.case_id,
                "sim_ts": n.sim_ts.isoformat(),
                "root_node": n.root_node,
                "verdict": n.verdict,
                "cause_kind": n.cause_kind,
                "cause_ref": n.cause_ref,
                "deciding_checks": n.deciding_checks,
                "decision": n.decision,
                "effect": n.effect,
            }
            for n in notes
        ]

    def loop(self) -> None:
        messages: list[dict[str, Any]] = [{"role": "user", "content": self._brief()}]
        nudged = False
        system = prompts.SELECT_V2 if self.book is not None else prompts.SELECT
        while not self.submitted:
            self._check()
            self.requests += 1
            request = LlmRequest(
                model=self.o.model,
                system=system,
                tools=self.o._tools,
                messages=messages,
                max_tokens=self.o.budget.tokens_per_call,
                key=f"investigate:{self.case.anomaly.id}:{self.requests}",
            )
            response, usage = call_model(self.o.client, request, self.o.journal, self.ctx.run_id, self.requests)
            self.inv.llm_calls += 1
            if response.stop_reason == "refusal":
                raise ProviderUnavailable("the model declined")
            messages.append({"role": "assistant", "content": response.content})
            results: list[dict[str, Any]] = []
            for block in response.content:
                kind = block.get("type")
                if kind == "text" and str(block.get("text", "")).strip():
                    self.o.journal.add(
                        "thought",
                        "PLAN",
                        self.case.as_of,
                        self.ctx.run_id,
                        actor="model",
                        text=scrub(str(block["text"]).strip(), self.facts),
                        anomaly_id=self.case.anomaly.id,
                        model=response.model,
                        input_tokens=usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens,
                        output_tokens=usage.output_tokens,
                        usd=usage.usd,
                    )
                elif kind == "tool_use":
                    text, is_error = self._call(str(block["name"]), dict(block.get("input") or {}))
                    results.append(
                        {"type": "tool_result", "tool_use_id": block["id"], "content": text, "is_error": is_error}
                    )
            if self.submitted:
                return
            if results:
                messages.append({"role": "user", "content": results})
                continue
            if response.stop_reason == "max_tokens":
                raise BudgetStop("a reply hit max_tokens")
            if nudged:
                self.stop = "ended without submitting"
                return
            nudged = True
            messages.append({"role": "user", "content": f"Call {SUBMIT} to finish."})

    # ------------------------------------------------------------------ one tool call
    def _call(self, name: str, raw: dict[str, Any]) -> tuple[str, bool]:
        if name == SUBMIT:
            self.claimed = str(raw.get("verdict")) if raw.get("verdict") in VERDICTS else None
            self.summary = str(raw.get("summary", ""))[:600]
            self.submitted = True
            self.o.journal.add(
                "thought",
                "VERIFY",
                self.case.as_of,
                self.ctx.run_id,
                actor="model",
                text=scrub(f"Submitted {self.claimed}: {self.summary}", self.facts),
                anomaly_id=self.case.anomaly.id,
            )
            return json.dumps({"status": "submitted; the gate decides"}), False
        hypothesis_id: str | None = None
        if self.calls >= self.o.budget.tool_calls:
            return json.dumps({"error": f"tool budget spent: call {SUBMIT}"}), True
        self.calls += 1
        if self.book is not None:
            if name == PROPOSE:
                return self._declare(raw)
            if name == "holdout_check" and not self.book.declared and not self.repaired:
                self.repaired = True
                return self._reject(name, f"declare hypotheses first: call {PROPOSE}, then test them")
            hypothesis_id = str(raw.pop("hypothesis_id")) if raw.get("hypothesis_id") is not None else None
        call_id = f"{self.ctx.run_id}:{self.calls}"
        meta = {k: str(raw[k]) for k in ("hypothesis", "prediction", "expect") if raw.get(k) is not None}
        args = naive_utc({k: v for k, v in raw.items() if k not in meta})
        self.o.journal.add(
            "tool_call",
            "ACT",
            self.case.as_of,
            self.ctx.run_id,
            actor="model",
            text=scrub(meta.get("prediction", ""), self.facts),
            anomaly_id=self.case.anomaly.id,
            tool=name,
            args={**args, "hypothesis_id": hypothesis_id} if hypothesis_id is not None else args,
        )
        obs = self._dispatch(call_id, name, args, meta)
        if self.book is not None:
            self._observe(hypothesis_id, obs)
        self.facts.add({"summary": obs.summary, "data": obs.data}, [r.receipt_id for r in obs.receipt_refs])
        self.o.journal.add(
            "tool_result",
            "OBSERVE",
            self.case.as_of,
            self.ctx.run_id,
            text=obs.summary,
            anomaly_id=self.case.anomaly.id,
            tool=name,
            observation=obs,
            receipt_links=obs.receipt_refs,
        )
        reply = {
            "summary": obs.summary,
            "availability": obs.availability,
            "outcome": obs.outcome,
            "ledger": obs.ledger.status if obs.ledger else None,
            "receipts": [r.receipt_id for r in obs.receipt_refs],
            "data": obs.data,
            "checks_left": self.inv.ledger.remaining,
            "tool_calls_left": self.o.budget.tool_calls - self.calls,
        }
        text = json.dumps(reply, separators=(",", ":"), default=str)
        if len(text) > MAX_RESULT_CHARS:
            reply["data"] = {"truncated": True}
            text = json.dumps(reply, separators=(",", ":"), default=str)
        return text, obs.availability in ("rejected", "error")

    # ------------------------------------------------------------------ v2: declared hypotheses
    def _reject(self, name: str, detail: str) -> tuple[str, bool]:
        self.o.journal.add(
            "rejected",
            "PLAN",
            self.case.as_of,
            self.ctx.run_id,
            text=detail,
            anomaly_id=self.case.anomaly.id,
            tool=name,
        )
        return json.dumps({"error": detail}), True

    def _declare(self, raw: dict[str, Any]) -> tuple[str, bool]:
        assert self.book is not None
        try:
            cards = self.book.declare(raw)
        except Declined as exc:
            return self._reject(PROPOSE, str(exc))
        self.o.journal.add(
            "hypothesis",
            "PLAN",
            self.case.as_of,
            self.ctx.run_id,
            actor="model",
            text=f"{len(cards)} competing hypotheses: " + "; ".join(f"{c.id} {c.statement}" for c in cards),
            anomaly_id=self.case.anomaly.id,
            tool=PROPOSE,
            args={"declared": [c.model_dump(mode="json") for c in cards]},
        )
        reply = {
            "status": "declared; code moves a card only on a judged check",
            "ids": [c.id for c in cards],
            "tool_calls_left": self.o.budget.tool_calls - self.calls,
        }
        return json.dumps(reply), False

    def _observe(self, hypothesis_id: str | None, obs: Observation) -> None:
        assert self.book is not None
        if obs.availability != "ok":
            return
        event = obs.args.get("event") if obs.tool == "holdout_check" else None
        event_ref = event.get("ref") if isinstance(event, dict) else None
        card = self.book.resolve(hypothesis_id, obs.tool, event_ref)
        if card is None:
            return
        if obs.tool == SQL:
            sql_move = self.book.observe_sql(card, obs.call_id, obs.outcome, obs.summary)
            if sql_move is not None:
                self._moved([sql_move])
            return
        node, segment = obs.args.get("node"), obs.args.get("segment")
        on_case = node is None or (node == self.case.focus and (segment or {}) == self.case.segment)
        move = self.book.observe(
            card, obs.call_id, obs.tool, obs.outcome, on_case=on_case, event_ref=event_ref, summary=obs.summary
        )
        if move is not None:
            self._moved([move])

    def _moved(self, moves: list[Any]) -> None:
        for move in moves:
            self.o.journal.add(
                "hypothesis",
                "VERIFY",
                self.case.as_of,
                self.ctx.run_id,
                text=f"{move.id} {move.status.replace('_', ' ')}: {move.reason}",
                anomaly_id=self.case.anomaly.id,
                args={"move": move.model_dump(mode="json")},
            )

    def _links(self, receipts: list[str]) -> list[ReceiptLink]:
        return [
            ReceiptLink(run_id=self.ctx.run_id, world_revision=self.ctx.world_revision, receipt_id=r) for r in receipts
        ]

    def _obs(self, call_id: str, name: str, args: dict[str, Any], meta: dict[str, str], **fields: Any) -> Observation:
        return Observation(
            call_id=call_id,
            tool=name,
            args=args,
            hypothesis=meta.get("hypothesis"),
            prediction=meta.get("prediction"),
            expect=meta.get("expect"),
            **fields,
        )

    def _agent_data(self, call_id: str) -> dict[str, Any]:
        return {"agent": {"run_id": self.ctx.run_id, "call_id": call_id, "model": self.o.model}}

    def _dispatch(self, call_id: str, name: str, args: dict[str, Any], meta: dict[str, str]) -> Observation:
        inv = self.inv
        try:
            if name == MARKET:
                return self._market(call_id, meta)
            if name == SQL and self.o.sql_check is not None:
                return self._sql(call_id, args, meta)
            if name not in TOOL_MODELS or name not in (*JUDGED, *OBSERVED):
                return self._obs(call_id, name, args, meta, summary=f"unknown tool {name}", availability="rejected")
            if name == "holdout_check":
                ev = self._listed(args.get("event"))
                if ev is None:
                    return self._obs(
                        call_id,
                        name,
                        args,
                        meta,
                        summary="that event is not one list_events returned in this run; pass it exactly",
                        availability="rejected",
                    )
                args = {**args, "event": ev.model_dump(mode="json")}
            TOOL_MODELS[name][0].model_validate(args)
            if name in OUTCOMES:
                hyp = Hypothesis(
                    statement=meta.get("hypothesis") or "-",
                    prediction=meta.get("prediction") or "-",
                    tool=name,
                    input=args,
                    expect=meta.get("expect") or OUTCOMES[name][0],
                    source=AGENT_SOURCE,
                )
                holder: dict[str, ToolOutput] = {}

                def run(h: Hypothesis) -> ToolOutput:
                    out = inv.tools.run(h.tool, h.input)
                    holder["out"] = out
                    return out

                tested = inv.ledger.test(hyp, run)
                if tested is None:
                    return self._obs(
                        call_id, name, args, meta, summary="check budget spent; submit", availability="rejected"
                    )
                entry, out = tested
                data = self._agent_data(call_id)
                if name == "holdout_check":
                    data["event"] = args["event"]
                inv._ledger_step(entry, out, data=data)
                if out is None:
                    return self._obs(
                        call_id, name, args, meta, summary=entry.summary, ledger=entry, availability="error"
                    )
                if name == "list_events":
                    self._remember(out)
                return self._obs(
                    call_id,
                    name,
                    args,
                    meta,
                    summary=entry.summary,
                    outcome=entry.outcome,
                    ledger=entry,
                    data=self._data(name, out),
                    receipt_refs=self._links(entry.receipts),
                )
            out = inv.tools.run(name, args)
            inv.step(
                TRAIL_KIND.get(name, "segment"),
                name,
                out.summary,
                "observed",
                hypothesis=meta.get("hypothesis"),
                prediction=meta.get("prediction"),
                receipts=list(out.receipts),
                data=self._agent_data(call_id),
            )
            return self._obs(
                call_id,
                name,
                args,
                meta,
                summary=out.summary,
                data=self._data(name, out),
                receipt_refs=self._links(list(out.receipts)),
            )
        except (ValidationError, KeyError, ValueError, ZeroDivisionError, RuntimeError) as exc:
            detail = (
                exc.errors()[0].get("msg", "invalid") if isinstance(exc, ValidationError) else str(exc).splitlines()[0]
            )
            return self._obs(
                call_id, name, args, meta, summary=f"{type(exc).__name__}: {detail}"[:300], availability="rejected"
            )

    def _sql(self, call_id: str, args: dict[str, Any], meta: dict[str, str]) -> Observation:
        assert self.o.sql_check is not None
        sql, predict = args.get("sql"), args.get("predict")
        if not isinstance(sql, str) or not isinstance(predict, dict):
            return self._obs(call_id, SQL, args, meta, summary="sql and predict are required", availability="rejected")
        inv = self.inv
        result = self.o.sql_check(inv.runner, sql, inv.as_of, predict, "detective")
        if not result.accepted:
            return self._obs(
                call_id, SQL, args, meta, summary=f"rejected by the SQL gate: {result.rule}", availability="rejected"
            )
        receipts = [result.receipt_id] if result.receipt_id else []
        inv.step(
            "holdout",
            SQL,
            result.summary,
            f"self-written check: {result.outcome or 'inconclusive'}",
            hypothesis=meta.get("hypothesis"),
            prediction=meta.get("prediction"),
            receipts=receipts,
            data={**self._agent_data(call_id), "sql": sql, "predict": predict, "outcome": result.outcome},
        )
        return self._obs(
            call_id,
            SQL,
            args,
            meta,
            summary=result.summary,
            outcome=result.outcome,
            data=dict(rounded({"rows": result.rows[:20]})),
            receipt_refs=self._links(receipts),
        )

    def _market(self, call_id: str, meta: dict[str, str]) -> Observation:
        inv = self.inv
        assessment = check_control_group(inv.runner, inv.graph, inv.anomaly, inv.as_of)
        if assessment is None:
            return self._obs(
                call_id,
                MARKET,
                {},
                meta,
                summary="not applicable: only drops of sessions, orders or gmv",
                availability="unavailable",
            )
        inv.step(
            "holdout",
            "check_control_group",
            assessment.reason,
            f"market verdict: {assessment.verdict}",
            hypothesis=meta.get("hypothesis"),
            prediction=meta.get("prediction"),
            receipts=[assessment.receipt_id],
            data={**self._agent_data(call_id), "market_control": assessment.model_dump(mode="json")},
        )
        data = assessment.model_dump(mode="json")
        data["series"] = data["series"][-6:]
        return self._obs(
            call_id,
            MARKET,
            {},
            meta,
            summary=assessment.reason,
            outcome=assessment.verdict,
            data=rounded(data),
            receipt_refs=self._links([assessment.receipt_id]),
        )

    def _data(self, name: str, out: ToolOutput) -> dict[str, Any]:
        data = out.model_dump(mode="json", exclude={"summary", "receipts"})
        if name == "list_events":
            data["events"] = [e.model_dump(mode="json") for e in self._grouped(out)]
        if name == "get_series":
            data["points"] = data.get("points", [])[-48:]
        return dict(rounded(data))

    @staticmethod
    def _grouped(out: ToolOutput) -> list[EvidenceRef]:
        from argus.investigate.procedure import group_batches

        return group_batches(list(getattr(out, "events", [])))

    def _remember(self, out: ToolOutput) -> None:
        for ev in self._grouped(out):
            if all((e.log, e.ref) != (ev.log, ev.ref) for e in self.listed):
                self.listed.append(ev)

    def _listed(self, raw: Any) -> EvidenceRef | None:
        if not isinstance(raw, dict):
            return None
        return next((e for e in self.listed if (e.log, e.ref) == (raw.get("log"), raw.get("ref"))), None)

    # ------------------------------------------------------------------ the gate
    def gate(self) -> Selection:
        """Admit only checks on the case itself; backfill what is mandatory and missing with Stage 2's own."""
        inv, c = self.inv, self.case
        backfilled: list[str] = []
        aligned_start, aligned_end = c.onset - EVENT_BEFORE, c.onset + EVENT_AFTER

        def on_case(e: LedgerEntry, tool: str) -> bool:
            h = e.hypothesis
            return (
                h.source == AGENT_SOURCE
                and h.tool == tool
                and h.input.get("node") == c.focus
                and (h.input.get("segment") or {}) == c.segment
            )

        agent_events = [e for e in self.listed if aligned_start <= e.ts <= aligned_end]
        if any(e.hypothesis.source == AGENT_SOURCE and e.hypothesis.tool == "list_events" for e in inv.ledger.entries):
            events = agent_events
        else:
            events = inv._events(c.focus, c.segment, c.onset)
            backfilled.append("list_events (the model did not list the logged changes)")

        supported: list[EvidenceRef] = []
        ruled_out: list[RuledOut] = []
        tested: set[tuple[str, str]] = set()
        for entry in inv.ledger.entries:
            if not on_case(entry, "holdout_check"):
                continue
            raw = entry.hypothesis.input.get("event") or {}
            ev = next((e for e in events if (e.log, e.ref) == (raw.get("log"), raw.get("ref"))), None)
            if ev is None:
                continue
            tested.add((ev.log, ev.ref))
            # decide on what the check showed, not on how the model framed it: a model that expected a rival
            # to be refuted gets a "validated" ledger entry for a refuted holdout
            if entry.outcome == "consistent":
                supported.append(ev)
            elif entry.outcome == "refuted":
                ruled_out.append(
                    RuledOut(
                        hypothesis=ev.description,
                        prediction=entry.hypothesis.prediction,
                        result="refuted",
                        reason=entry.summary,
                        evidence=ev,
                        receipts=entry.receipts,
                    )
                )
        untested = [e for e in events if (e.log, e.ref) not in tested]
        if untested:
            more_supported, more_ruled = inv._test_events(untested, c.focus, c.segment, c.root_rel, c.onset)
            supported += more_supported
            ruled_out += more_ruled
            backfilled.append(f"holdout_check for {len(untested)} untested candidate(s)")

        placebo = next((e for e in reversed(inv.ledger.entries) if on_case(e, "placebo_test")), None)
        placebo = canonical_placebo(placebo) if placebo is not None else None
        if placebo is None:
            placebo = inv._placebo(c.focus, c.segment, c.anomaly.direction)
            backfilled.append("placebo_test on the root segment")
        for line in backfilled:
            self.o.journal.add(
                "gate", "VERIFY", c.as_of, self.ctx.run_id, text=f"backfilled: {line}", anomaly_id=c.anomaly.id
            )
        if self.book is not None:
            self._moved(self.book.settle(supported, ruled_out, placebo.outcome if placebo is not None else None))
        return Selection(
            run_id=self.ctx.run_id,
            events=events,
            supported=supported,
            ruled_out=ruled_out,
            placebo=placebo,
            claimed=self.claimed,
            summary=self.summary,
            llm_calls=self.requests,
            stop=self.stop,
            backfilled=backfilled,
        )
