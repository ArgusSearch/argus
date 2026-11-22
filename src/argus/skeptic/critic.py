"""The counter-check (profile v2, feature `critic`): a second model tries to break a supported cause.

When Stage 2's rules would admit SUPPORTED_CAUSE, the investigation asks the selector to `challenge` it
before the findings are assembled (`argus.investigate.procedure`). The critic is a second model (Opus,
`ARGUS_AGENT_CRITIC_MODEL`) in a fresh context: it sees the case packet, the host's trail with receipts and
the claimed cause, never the detective's thoughts or hypotheses. Its one instruction is to find the
cheapest check that would prove the cause wrong, with at most three tool calls (the Reflexion pattern of a
second pass over a finished attempt, Shinn et al. 2023, arXiv 2303.11366, implemented fresh).

The model's opinion decides nothing. Deterministic rules read the outcomes of its checks (`counter_verdict`):

| rule | counter-evidence                                                                  | result  |
|------|-----------------------------------------------------------------------------------|---------|
| R1   | a holdout of the supported event on the case's node and segment comes back refuted | refuted |
| R2   | a placebo on the case's node and segment comes back recurring                      | refuted |
| R3   | a distinct event near the onset, with equal or narrower scope, has a consistent    | weakened|
|      | holdout on the case's node and segment; simultaneous events are inconclusive       |         |
| R4   | a `sql_check` whose prediction states what the cause implies fails (feature `sql`) | weakened|

`ARGUS_AGENT_CRITIC_RULES` (default `R1,R2,R3`) narrows the rules, so each rule can be cut on its own.
R4 is opt-in until the relevance of a model-written prediction can be established.
| -    | no rule fired                                                                     | upheld  |

Any rule that fires downgrades the verdict; nothing the critic does can grant one (monotone safety). If
the critic cannot run (provider error, cassette miss) the verdict stands as decided, in the same tick,
and one line says "counter-check unavailable". Critic checks run on their own ledger (budget three), so
they never spend the detective's checks and never count toward a verdict.

Activity: the critic writes `tool_call` and `tool_result` lines with role `skeptic` and call ids
`<run_id>:c<n>`, its visible sentences as `thought` lines, and one `critic` line once the rules decided
(`args`: the `Challenge` fields plus `model`). Recording keys are `critic:<anomaly_id>:<round>`.
"""

from __future__ import annotations

import importlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from argus.agent import prompts
from argus.agent.numbers import FactBook, scrub
from argus.agent.profile import V2, Profile
from argus.agent.provider import ProviderUnavailable, usage_record
from argus.agent.tools import c6_schema, naive_utc, rounded
from argus.agent.types import Challenge, LlmClient, LlmRequest, Observation, ReceiptLink, SqlCheckRunner
from argus.contracts.findings import EvidenceRef
from argus.contracts.tools import TOOL_MODELS
from argus.investigate.ledger import Hypothesis, Ledger, LedgerEntry

if TYPE_CHECKING:
    from argus.agent.investigate import Case, Selection
    from argus.agent.journal import Journal
    from argus.investigate.procedure import StageTwoInvestigation

CRITIC_SOURCE = "critic"
CRITIC_MODEL = os.environ.get("ARGUS_AGENT_CRITIC_MODEL", "claude-opus-5-5")
EVENT_BEFORE = timedelta(hours=3)
EVENT_AFTER = timedelta(hours=1)
MAX_RESULT_CHARS = 5000
CHECKS = ("list_events", "holdout_check", "placebo_test", "get_series")
SQL = "sql_check"
SUBMIT = "submit_challenge"
RULES = ("R1", "R2", "R3", "R4")


def configured_rules() -> frozenset[str]:
    raw = os.environ.get("ARGUS_AGENT_CRITIC_RULES")
    chosen = {r.strip().upper() for r in raw.split(",") if r.strip()} if raw is not None else {"R1", "R2", "R3"}
    unknown = sorted(chosen - set(RULES))
    if unknown:
        raise ValueError(f"unknown critic rule(s) {unknown}; known: {list(RULES)}")
    return frozenset(chosen)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class CriticBudget:
    """Caps of one counter-check (environment overrides: ARGUS_AGENT_CRITIC_MAX_*)."""

    requests: int = _env_int("ARGUS_AGENT_CRITIC_MAX_REQUESTS", 3)
    tool_calls: int = _env_int("ARGUS_AGENT_CRITIC_MAX_TOOL_CALLS", 3)
    usd: float = float(os.environ.get("ARGUS_AGENT_CRITIC_MAX_USD", 0.20))
    wall_seconds: float = float(os.environ.get("ARGUS_AGENT_CRITIC_MAX_SECONDS", 45))
    tokens_per_call: int = 3000


class CriticStop(RuntimeError):
    pass


def sql_check_spec() -> dict[str, Any]:
    return {
        "name": SQL,
        "description": "One read-only SELECT over the as-of views (fact_*, log_*, dim_advertiser), with a "
        "prediction the host judges on the rows: the mean of `value` in group `a` against group `b`.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "one SELECT, no comments, at most 2000 characters"},
                "hypothesis": {"type": "string"},
                "prediction": {"type": "string", "description": "what the rows show if the cause holds"},
                "predict": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "group": {"type": "string"},
                        "a": {"type": "array", "items": {"type": "string"}},
                        "b": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"const": "rest"}]},
                        "relation": {"type": "string", "enum": ["a_lt_b", "a_gt_b", "a_eq_b"]},
                        "min_gap": {"type": "number"},
                    },
                    "required": ["value", "group", "a", "b", "relation", "min_gap"],
                    "additionalProperties": False,
                },
            },
            "required": ["sql", "hypothesis", "prediction", "predict"],
            "additionalProperties": False,
        },
    }


def critic_specs(sql: bool = False) -> list[dict[str, Any]]:
    descriptions = {
        "list_events": "Log entries (deploys, provider status, budgets, calendar) in a time range, optionally only "
        "those whose scope covers a segment.",
        "holdout_check": "Is the node normal where the event did NOT apply? Pass an event exactly as listed. "
        "consistent = the change sits where the event applies; refuted = it moves outside too.",
        "placebo_test": "Do the same hours of earlier weeks show deviations this large? unusual = no; recurring = yes.",
        "get_series": "Hourly values and expectation (same hour, 4 earlier weeks) of a node in a segment, <= 48 h.",
    }
    specs: list[dict[str, Any]] = []
    for name in CHECKS:
        specs.append(
            {
                "name": name,
                "description": descriptions[name] + " Runs SQL with a receipt.",
                "input_schema": c6_schema(name),
            }
        )
    if sql:
        specs.append(sql_check_spec())
    specs.append(
        {
            "name": SUBMIT,
            "description": "End the counter-check. Deterministic rules decide from the checks you ran; state "
            "whether you think the cause stands.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "opinion": {"type": "string", "enum": ["upheld", "weakened", "refuted"]},
                    "summary": {"type": "string", "description": "two sentences, no numbers"},
                },
                "required": ["opinion", "summary"],
                "additionalProperties": False,
            },
        }
    )
    return specs


@dataclass
class CriticCheck:
    """One check the critic ran, as the rules read it."""

    call_id: str
    tool: str
    node: str | None
    segment: dict[str, str]
    event: EvidenceRef | None
    outcome: str | None
    summary: str
    receipts: list[str]
    availability: str = "ok"

    def to_json(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool": self.tool,
            "node": self.node,
            "segment": self.segment,
            "event_ref": self.event.ref if self.event else None,
            "outcome": self.outcome,
            "summary": self.summary,
            "receipts": self.receipts,
            "availability": self.availability,
        }


@dataclass(frozen=True)
class Ruling:
    verdict: Literal["upheld", "weakened", "refuted"]
    rule: str | None
    reason: str


def counter_verdict(
    checks: list[CriticCheck], case: Case, supported: EvidenceRef, rules: frozenset[str] = frozenset(RULES)
) -> Ruling:
    """Rules R1-R4 over the critic's judged checks. The first rule that fires in this order decides."""

    def on_case(c: CriticCheck) -> bool:
        return c.availability == "ok" and c.node == case.focus and c.segment == case.segment

    same = (supported.log, supported.ref)
    for c in checks if "R1" in rules else ():
        hit = on_case(c) and c.tool == "holdout_check" and c.event and (c.event.log, c.event.ref) == same
        if hit and c.outcome == "refuted":
            return Ruling("refuted", "R1", f"the holdout of {supported.ref} is refuted: {c.summary}")
    for c in checks if "R2" in rules else ():
        if on_case(c) and c.tool == "placebo_test" and c.outcome == "recurring":
            return Ruling("refuted", "R2", f"deviations like this recur in earlier weeks: {c.summary}")
    if "R3" in rules:
        start, end = case.onset - EVENT_BEFORE, case.onset + EVENT_AFTER
        for c in checks:
            ev = c.event
            if not (on_case(c) and c.tool == "holdout_check" and ev is not None and c.outcome == "consistent"):
                continue
            # A holdout cannot distinguish simultaneous changes within the same scope. In S4, the
            # deployment and per-advertiser budget log entries record the same pacing change.
            if (ev.log, ev.ref) == same or ev.ts == supported.ts or not start <= ev.ts <= end:
                continue
            if all(key in ev.scope and set(ev.scope[key]) <= set(values) for key, values in supported.scope.items()):
                return Ruling(
                    "weakened",
                    "R3",
                    f"{ev.description} ({ev.ref}) fits the change as well as {supported.ref}: {c.summary}",
                )
    if "R4" in rules:
        for c in checks:
            if c.tool == SQL and c.availability == "ok" and c.outcome == "fails":
                return Ruling("weakened", "R4", f"a self-written check contradicts the cause: {c.summary}")
    return Ruling("upheld", None, "")


class LlmCritic:
    """Implements the `Critic` protocol of the agent interface. One instance per runtime."""

    def __init__(
        self,
        client: LlmClient,
        journal: Journal,
        profile: Profile = V2,
        budget: CriticBudget | None = None,
        model: str = CRITIC_MODEL,
        world_revision: str = "factual",
        sql_runner: SqlCheckRunner | None = None,
        rules: frozenset[str] | None = None,
    ) -> None:
        self.client = client
        self.journal = journal
        self.profile = profile
        self.budget = budget or CriticBudget()
        self.model = model
        self.world_revision = world_revision
        self.sql_runner = sql_runner if sql_runner is not None else (load_sql_check() if profile.on("sql") else None)
        self.rules = rules if rules is not None else configured_rules()
        self._tools = critic_specs(sql=self.sql_runner is not None)

    def challenge(
        self, inv: StageTwoInvestigation, case: Case, selection: Selection, supported: EvidenceRef
    ) -> Challenge:
        run = _CriticRun(self, inv, case, selection, supported)
        error = ""
        try:
            run.loop()
        except CriticStop as exc:
            run.stop = f"budget: {exc}"
        except Exception as exc:  # provider errors, cassette misses, SDK types: the verdict must stand
            error = f"{type(exc).__name__}: {exc}"[:300]
        ruling = counter_verdict(run.checks, case, supported, self.rules)
        checks = [c.to_json() for c in run.checks]
        if error or (ruling.rule is None and not (run.checks or run.submitted)):
            why = error or run.stop or "no check ran"
            challenge = Challenge(
                verdict="unavailable", downgrade=False, reason=f"counter-check unavailable: {why}", checks=checks
            )
        elif ruling.rule is None:
            tried = len(run.checks)
            challenge = Challenge(
                verdict="upheld",
                downgrade=False,
                reason=f"{tried} attempt(s) to falsify {supported.ref}, none succeeded",
                checks=checks,
            )
        else:
            challenge = Challenge(
                verdict=ruling.verdict, downgrade=True, reason=f"{ruling.rule}: {ruling.reason}"[:600], checks=checks
            )
        self.journal.add(
            "critic",
            "VERIFY",
            case.as_of,
            selection.run_id,
            role="skeptic",
            text=f"counter-check {challenge.verdict}: {challenge.reason}"
            + (f" (the critic's own opinion: {run.opinion})" if run.opinion else ""),
            anomaly_id=case.anomaly.id,
            model=self.model,
            args={**challenge.model_dump(mode="json"), "model": self.model},
            receipt_links=[r for c in run.checks for r in run.links(c.receipts)],
        )
        return challenge


def load_sql_check() -> SqlCheckRunner | None:
    """`argus.evidence.sqlgate.run_check` when the SQL gate is installed, else None (no `sql_check` tool)."""
    try:
        sqlgate = importlib.import_module("argus.evidence.sqlgate")
    except ImportError:
        return None
    runner: SqlCheckRunner | None = getattr(sqlgate, "run_check", None)
    return runner


@dataclass
class _CriticRun:
    o: LlmCritic
    inv: StageTwoInvestigation
    case: Case
    selection: Selection
    supported: EvidenceRef
    checks: list[CriticCheck] = field(default_factory=list)
    listed: list[EvidenceRef] = field(default_factory=list)
    opinion: str | None = None
    stop: str = ""
    submitted: bool = False
    requests: int = 0
    calls: int = 0

    def __post_init__(self) -> None:
        self.started = time.monotonic()
        self.ledger = Ledger(budget=self.o.budget.tool_calls)
        self.listed = list(self.selection.events)
        self.facts = FactBook()
        self.facts.add(self.case.anomaly.model_dump(mode="json"), list(self.case.anomaly.receipts) or ["anomaly"])
        for step in self.inv.trail:
            self.facts.add({"result": step.result, "decision": step.decision, "data": step.data}, step.receipts)
        self.first_usage = len([u for u in self.o.journal.usage if u.run_id == self.selection.run_id])

    @property
    def run_id(self) -> str:
        return self.selection.run_id

    def links(self, receipts: list[str]) -> list[ReceiptLink]:
        return [ReceiptLink(run_id=self.run_id, world_revision=self.o.world_revision, receipt_id=r) for r in receipts]

    # ------------------------------------------------------------------ budget
    def _usage(self) -> list[Any]:
        return [u for u in self.o.journal.usage if u.run_id == self.run_id][self.first_usage :]

    def _check(self) -> None:
        b = self.o.budget
        usage = self._usage()
        if self.requests >= b.requests:
            raise CriticStop(f"{b.requests} model requests")
        if any(u.usd is None for u in usage):
            raise CriticStop("a model without a tariff")
        if sum(u.usd or 0.0 for u in usage) >= b.usd:
            raise CriticStop(f"USD {b.usd}")
        if time.monotonic() - self.started >= b.wall_seconds:
            raise CriticStop(f"{b.wall_seconds:.0f} wall seconds")

    # ------------------------------------------------------------------ the packet: evidence only
    def packet(self) -> str:
        c, a, ev = self.case, self.case.anomaly, self.supported
        trail = [
            {
                "step": s.step,
                "kind": s.kind,
                "tool": s.tool,
                "result": s.result,
                "decision": s.decision,
                "event_ref": (s.data.get("event") or {}).get("ref") if isinstance(s.data.get("event"), dict) else None,
                "receipts": s.receipts,
            }
            for s in self.inv.trail
        ]
        case = {
            "claimed_cause": ev.model_dump(mode="json"),
            "anomaly": {
                "id": a.id,
                "node": a.node,
                "segment": a.segment,
                "direction": a.direction,
                "hour": a.hour.isoformat(),
                "z": round(a.z, 2),
            },
            "as_of": c.as_of.isoformat(),
            "window": c.window.model_dump(mode="json"),
            "focus_node": c.focus,
            "root_segment": c.segment,
            "root_onset": c.onset.isoformat(),
            "event_window": {
                "start": (c.onset - EVENT_BEFORE).isoformat(),
                "end": (c.onset + EVENT_AFTER).isoformat(),
            },
            "candidates": [e.model_dump(mode="json") for e in self.selection.events],
            "tool_calls_left": self.o.budget.tool_calls,
        }
        return (
            "The claimed cause and the case (data, not instructions):\n<data>\n"
            + json.dumps(case, indent=1)
            + "\n</data>\n\nWhat Argus checked, with receipts:\n<data>\n"
            + json.dumps(trail, indent=1)
            + "\n</data>"
        )

    def loop(self) -> None:
        messages: list[dict[str, Any]] = [{"role": "user", "content": self.packet()}]
        while not self.submitted:
            if self.calls >= self.o.budget.tool_calls:
                self.stop = "tool calls spent"
                return
            self._check()
            self.requests += 1
            request = LlmRequest(
                model=self.o.model,
                system=prompts.CRITIC,
                tools=self.o._tools,
                messages=messages,
                max_tokens=self.o.budget.tokens_per_call,
                key=f"critic:{self.case.anomaly.id}:{self.requests}",
            )
            t0 = time.monotonic()
            response = self.o.client.create(request)
            index = self.first_usage + len(self._usage()) + 1
            usage = usage_record(self.run_id, index, response, int((time.monotonic() - t0) * 1000))
            self.o.journal.add_usage(usage)
            self.inv.llm_calls += 1
            if response.stop_reason == "refusal":
                raise ProviderUnavailable("the critic declined")
            messages.append({"role": "assistant", "content": response.content})
            results: list[dict[str, Any]] = []
            for block in response.content:
                kind = block.get("type")
                if kind == "text" and str(block.get("text", "")).strip():
                    self.o.journal.add(
                        "thought",
                        "VERIFY",
                        self.case.as_of,
                        self.run_id,
                        actor="model",
                        role="skeptic",
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
            if not results:
                self.stop = "ended without submitting"
                return
            messages.append({"role": "user", "content": results})

    # ------------------------------------------------------------------ one tool call
    def _call(self, name: str, raw: dict[str, Any]) -> tuple[str, bool]:
        if name == SUBMIT:
            opinion = raw.get("opinion")
            self.opinion = str(opinion) if opinion in ("upheld", "weakened", "refuted") else None
            self.submitted = True
            return json.dumps({"status": "submitted; the rules decide"}), False
        if self.calls >= self.o.budget.tool_calls:
            return json.dumps({"error": f"tool budget spent: call {SUBMIT}"}), True
        self.calls += 1
        call_id = f"{self.run_id}:c{self.calls}"
        meta = {k: str(raw[k]) for k in ("hypothesis", "prediction", "expect") if raw.get(k) is not None}
        args = naive_utc({k: v for k, v in raw.items() if k not in meta})
        self.o.journal.add(
            "tool_call",
            "ACT",
            self.case.as_of,
            self.run_id,
            actor="model",
            role="skeptic",
            text=scrub(meta.get("prediction", ""), self.facts),
            anomaly_id=self.case.anomaly.id,
            tool=name,
            args=args,
        )
        obs, check = self._dispatch(call_id, name, args, meta)
        if check is not None:
            self.checks.append(check)
        self.facts.add({"summary": obs.summary, "data": obs.data}, [r.receipt_id for r in obs.receipt_refs])
        self.o.journal.add(
            "tool_result",
            "OBSERVE",
            self.case.as_of,
            self.run_id,
            role="skeptic",
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
            "receipts": [r.receipt_id for r in obs.receipt_refs],
            "data": obs.data,
            "tool_calls_left": self.o.budget.tool_calls - self.calls,
        }
        text = json.dumps(reply, separators=(",", ":"), default=str)
        if len(text) > MAX_RESULT_CHARS:
            reply["data"] = {"truncated": True}
            text = json.dumps(reply, separators=(",", ":"), default=str)
        return text, obs.availability in ("rejected", "error")

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
        return {"agent": {"run_id": self.run_id, "call_id": call_id, "model": self.o.model, "role": CRITIC_SOURCE}}

    def _rejected(
        self, call_id: str, name: str, args: dict[str, Any], meta: dict[str, str], summary: str
    ) -> tuple[Observation, CriticCheck | None]:
        return self._obs(call_id, name, args, meta, summary=summary, availability="rejected"), None

    def _dispatch(
        self, call_id: str, name: str, args: dict[str, Any], meta: dict[str, str]
    ) -> tuple[Observation, CriticCheck | None]:
        try:
            if name == SQL and self.o.sql_runner is not None:
                return self._sql(call_id, args, meta)
            if name not in CHECKS:
                return self._rejected(call_id, name, args, meta, f"unknown tool {name}")
            event: EvidenceRef | None = None
            if name == "holdout_check":
                event = self._listed(args.get("event"))
                if event is None:
                    return self._rejected(
                        call_id, name, args, meta, "that event is not a listed candidate; pass it exactly"
                    )
                args = {**args, "event": event.model_dump(mode="json")}
            TOOL_MODELS[name][0].model_validate(args)
            if name == "get_series":
                series = self.inv.tools.run(name, args)
                self.inv.step(
                    "segment",
                    name,
                    series.summary,
                    "observed",
                    receipts=list(series.receipts),
                    data=self._agent_data(call_id),
                )
                points = series.model_dump(mode="json", exclude={"summary", "receipts"})
                points["points"] = points.get("points", [])[-24:]
                return (
                    self._obs(
                        call_id,
                        name,
                        args,
                        meta,
                        summary=series.summary,
                        data=dict(rounded(points)),
                        receipt_refs=self.links(list(series.receipts)),
                    ),
                    None,
                )
            # the ledger's usual framing, so the trail reads like Stage 2's; the rules read outcomes, not this
            expect = {"holdout_check": "consistent", "placebo_test": "unusual", "list_events": "found"}[name]
            hyp = Hypothesis(
                statement=meta.get("hypothesis") or "-",
                prediction=meta.get("prediction") or "-",
                tool=name,
                input=args,
                expect=expect,
                source=CRITIC_SOURCE,
            )
            tested = self.ledger.test(hyp, lambda h: self.inv.tools.run(h.tool, h.input))
            if tested is None:
                return self._rejected(call_id, name, args, meta, "check budget spent; submit")
            entry, out = tested
            data = self._agent_data(call_id)
            if event is not None:
                data["event"] = args["event"]
            self.inv._ledger_step(entry, out, data=data)
            if out is None:
                obs = self._obs(call_id, name, args, meta, summary=entry.summary, ledger=entry, availability="error")
                return obs, None
            shown = out.model_dump(mode="json", exclude={"summary", "receipts"})
            if name == "list_events":
                self._remember(out)
                shown["events"] = [e.model_dump(mode="json") for e in self._grouped(out)]
            check = self._check_of(call_id, entry, args, event)
            obs = self._obs(
                call_id,
                name,
                args,
                meta,
                summary=entry.summary,
                outcome=entry.outcome,
                ledger=entry,
                data=dict(rounded(shown)),
                receipt_refs=self.links(entry.receipts),
            )
            return obs, check
        except (ValidationError, KeyError, ValueError, ZeroDivisionError, RuntimeError) as exc:
            detail = (
                exc.errors()[0].get("msg", "invalid") if isinstance(exc, ValidationError) else str(exc).splitlines()[0]
            )
            return self._rejected(call_id, name, args, meta, f"{type(exc).__name__}: {detail}"[:300])

    def _check_of(
        self, call_id: str, entry: LedgerEntry, args: dict[str, Any], event: EvidenceRef | None
    ) -> CriticCheck:
        return CriticCheck(
            call_id=call_id,
            tool=entry.hypothesis.tool,
            node=args.get("node"),
            segment=dict(args.get("segment") or {}),
            event=event,
            outcome=entry.outcome,
            summary=entry.summary,
            receipts=list(entry.receipts),
        )

    def _sql(self, call_id: str, args: dict[str, Any], meta: dict[str, str]) -> tuple[Observation, CriticCheck | None]:
        sql, predict = str(args.get("sql") or ""), args.get("predict")
        if not isinstance(predict, dict) or self.o.sql_runner is None:
            return self._rejected(call_id, SQL, args, meta, "predict is required")
        judgement = self.o.sql_runner(
            self.inv.runner, sql, self.inv.as_of, predict, f"critic sql_check: {meta.get('hypothesis', '-')}"[:200]
        )
        if not judgement.accepted:
            return self._rejected(call_id, SQL, args, meta, f"rejected by the SQL gate: {judgement.rule or '-'}")
        receipts = [judgement.receipt_id] if judgement.receipt_id else []
        outcome, summary = judgement.outcome, judgement.summary
        self.inv.step(
            "holdout",
            SQL,
            summary,
            f"self-written check: {outcome or 'inconclusive'}",
            hypothesis=meta.get("hypothesis"),
            prediction=meta.get("prediction"),
            receipts=receipts,
            data={**self._agent_data(call_id), "sql": sql, "predict": predict, "outcome": outcome},
        )
        rows = judgement.rows[:20]
        check = CriticCheck(
            call_id=call_id,
            tool=SQL,
            node=None,
            segment={},
            event=None,
            outcome=outcome,
            summary=summary,
            receipts=receipts,
        )
        obs = self._obs(
            call_id,
            SQL,
            args,
            meta,
            summary=summary,
            outcome=outcome,
            data=dict(rounded({"rows": rows})),
            receipt_refs=self.links(receipts),
        )
        return obs, check

    @staticmethod
    def _grouped(out: Any) -> list[EvidenceRef]:
        from argus.investigate.procedure import group_batches

        return group_batches(list(getattr(out, "events", [])))

    def _remember(self, out: Any) -> None:
        for ev in self._grouped(out):
            if all((e.log, e.ref) != (ev.log, ev.ref) for e in self.listed):
                self.listed.append(ev)

    def _listed(self, raw: Any) -> EvidenceRef | None:
        if not isinstance(raw, dict):
            return None
        return next((e for e in self.listed if (e.log, e.ref) == (raw.get("log"), raw.get("ref"))), None)
