"""The investigation board (docs/ext/agent.md "Board"): a read model over what every run already records.

`build_board` is a pure function of activity records, C4 findings and the run summary. It needs no model and no
new recording, so it works on the sealed v1 presentations, on a live journal and on a Stage-2-only incident
(no agent run at all). Same input, same JSON: the board of a playback cursor is a function of what is visible
at that cursor, so cards appear `open` and flip as the playback advances.

Derivation (deterministic; the verdict itself is never re-decided here):

| check                                   | card                                  | status                            |
|-----------------------------------------|---------------------------------------|-----------------------------------|
| list_events (agent)                     | one `event` card per listed candidate | open until a holdout judges it    |
| holdout_check on an event ref           | `event`, subject = ref                | consistent: supported, refuted:   |
|                                         |                                       | ruled out, else inconclusive      |
| freshness and identities steps          | `data` "the data is late or broken"   | complete and holding: ruled out   |
| calendar or plan-follow step            | `planned`                             | stop EXPECTED: supported          |
| market_control / check_control_group    | `market`                              | market: supported, us: ruled out  |
| mix_rate_split                          | `mix`                                 | mix: supported, rate: ruled out   |
| placebo_test                            | `recurring`                           | recurring: supported, unusual:    |
|                                         |                                       | ruled out                         |
| findings.ruled_out not matched above    | `other`, its own text                 | refuted: ruled out, else          |
|                                         |                                       | inconclusive                      |

Once the findings exist they are authoritative: an event card stays `supported` only when the verdict is
SUPPORTED_CAUSE and names that event (`findings.root.evidence`); a rival that was merely consistent becomes
`inconclusive`. After the run no card is `open`: what was never judged is `not_tested`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic import ValidationError

from argus.agent.chain import chain_of, links, tagged
from argus.agent.types import (
    BOARD_VERSION,
    HYPOTHESIS_STATUSES,
    ActivityRecord,
    Board,
    Challenge,
    CheckRef,
    CheckStatus,
    CostLine,
    CostView,
    CriticView,
    DeclaredHypothesis,
    Discarded,
    HypothesisCard,
    HypothesisKind,
    HypothesisMove,
    HypothesisStatus,
    Precedent,
    ProfileName,
    ReceiptLink,
    Role,
    RunSummary,
    StepGroup,
    StepPhase,
)
from argus.contracts.findings import Findings, Incident, TrailStep, Verdict

V2_KINDS = frozenset({"hypothesis", "critic", "memory"})
DETECTIVE_CAPS = (0.50, 12)
CRITIC_CAP_USD = 0.20
CRITIC_CAP_TOOL_CALLS = 3
_CALLS = re.compile(r"^(\d+) model call\(s\)")
_GATE = re.compile(r"^verdict ([A-Z_]+) \(model claimed ([A-Za-z_]+)\)$")

_STATEMENTS: dict[HypothesisKind, str] = {
    "data": "the data is late or broken",
    "planned": "a planned change explains it",
    "market": "the whole market moved",
    "mix": "a mix shift explains it",
    "recurring": "this recurs every week",
}
_SUPPORTS: dict[str, dict[str, HypothesisStatus]] = {
    # tool -> outcome -> status of the card the tool judges
    "holdout_check": {"consistent": "supported", "refuted": "ruled_out"},
    "placebo_test": {"recurring": "supported", "unusual": "ruled_out"},
    "market_control": {"market": "supported", "us": "ruled_out"},
    "check_control_group": {"market": "supported", "us": "ruled_out"},
    "mix_rate_split": {"mix": "supported", "rate": "ruled_out"},
    "check_freshness": {"incomplete": "supported", "complete": "ruled_out"},
    "check_identities": {"broken": "supported", "hold": "ruled_out"},
}
_CARD_OF_TOOL: dict[str, HypothesisKind] = {
    "placebo_test": "recurring",
    "market_control": "market",
    "check_control_group": "market",
    "mix_rate_split": "mix",
    "check_freshness": "data",
    "check_identities": "data",
}
_CHECK_STATUS: dict[HypothesisStatus, CheckStatus] = {
    "supported": "validated",
    "ruled_out": "refuted",
    "inconclusive": "inconclusive",
}
_TITLES: dict[StepPhase, tuple[str, Role]] = {
    "opening": ("Opening checks", "detective"),
    "hypotheses": ("Candidates", "detective"),
    "checks": ("Checks", "detective"),
    "critic": ("Counter-check", "skeptic"),
    "verdict": ("Verdict", "skeptic"),
    "report": ("Report", "narrator"),
    "action": ("Action", "operator"),
    "effect": ("Effect", "operator"),
    "ask": ("Question", "narrator"),
}


@dataclass
class _Card:
    key: str
    kind: HypothesisKind
    statement: str
    subject: str | None = None
    source: Literal["host", "model", "critic"] = "host"
    parent: str | None = None
    decisive_check: str | None = None
    status: HypothesisStatus = "open"
    reason: str = "not judged yet"
    checks: list[CheckRef] = field(default_factory=list)


class _Book:
    """Cards in order of first appearance, addressable by subject key and by the model's own ids."""

    def __init__(self) -> None:
        self.cards: dict[str, _Card] = {}
        self.alias: dict[str, str] = {}

    def get(self, key: str, kind: HypothesisKind, statement: str, **extra: Any) -> _Card:
        key = self.alias.get(key, key)
        if key not in self.cards:
            self.cards[key] = _Card(key=key, kind=kind, statement=statement, **extra)
        return self.cards[key]

    def find(self, key: str) -> _Card | None:
        return self.cards.get(self.alias.get(key, key))

    def judge(self, card: _Card, check: CheckRef, status: HypothesisStatus | None) -> None:
        if check.call_id is None or all(c.call_id != check.call_id for c in card.checks):
            card.checks.append(check)
        if status is not None:
            card.status = status
            card.decisive_check = card.decisive_check or check.tool
            verb = {"supported": "supported by", "ruled_out": "ruled out by", "inconclusive": "inconclusive:"}
            card.reason = f"{verb.get(status, status)} {check.tool}: {check.summary}"


def _ledger_outcome(step: TrailStep) -> str | None:
    ledger = step.data.get("ledger")
    if isinstance(ledger, dict):
        return cast(str | None, ledger.get("outcome"))
    market = step.data.get("market_control")
    if isinstance(market, dict):
        return cast(str | None, market.get("verdict"))
    return None


def _event_ref(raw: Any) -> tuple[str, str] | None:
    if isinstance(raw, dict) and isinstance(raw.get("ref"), str):
        return raw["ref"], str(raw.get("description") or raw["ref"])
    return None


def _status_of(tool: str, outcome: str | None) -> HypothesisStatus:
    return _SUPPORTS.get(tool, {}).get(outcome or "", "inconclusive")


def _check_status(status: HypothesisStatus | None) -> CheckStatus:
    return _CHECK_STATUS.get(status, "observed") if status is not None else "observed"


def _call_args(records: Sequence[ActivityRecord], index: int) -> dict[str, Any]:
    """The tool_call record that journaled this result's call (the one right before it, same tool)."""
    for prev in reversed(records[:index]):
        if prev.kind == "tool_call":
            return dict(prev.args or {}) if prev.tool == records[index].tool else {}
        if prev.kind == "tool_result":
            return {}
    return {}


def _is_critic(record: ActivityRecord) -> bool:
    obs = record.observation
    return obs is not None and ":c" in obs.call_id


def _run_id_of(findings: Findings | None) -> str | None:
    for step in findings.trail if findings is not None else []:
        agent = step.data.get("agent")
        if isinstance(agent, dict) and isinstance(agent.get("run_id"), str):
            return cast(str, agent["run_id"])
    return None


def revision_of(run_id: str | None, records: Sequence[ActivityRecord]) -> str:
    if run_id is None:
        return "factual"
    return next(
        (link.world_revision for record in records if record.run_id == run_id for link in record.receipt_links),
        "factual",
    )


def model_calls(records: Iterable[ActivityRecord]) -> int | None:
    """The billed number of model calls from the host's closing line ('4 model call(s), USD ...'), when logged.

    Not every call leaves a record with a model (a reply with only a tool call writes none), so counting
    records undercounts a recorded run."""
    for record in records:
        if record.kind == "run_finished" and (match := _CALLS.match(record.text)):
            return int(match.group(1))
    return None


class _Derivation:
    def __init__(
        self,
        records: Sequence[ActivityRecord],
        findings: Findings | None,
        run_id: str | None,
        world_revision: str,
    ) -> None:
        self.records = records
        self.findings = findings
        self.run_id = run_id
        self.revision = world_revision
        self.book = _Book()
        self.critic_checks: list[CheckRef] = []
        self.pending_moves: dict[str, HypothesisMove] = {}
        self.steps_by_call: dict[str, int] = {}
        for step in findings.trail if findings is not None else []:
            agent = step.data.get("agent")
            if isinstance(agent, dict) and isinstance(agent.get("call_id"), str):
                self.steps_by_call[agent["call_id"]] = step.step

    def links(self, receipts: Iterable[str | None]) -> list[ReceiptLink]:
        return links(receipts, self.run_id, self.revision)

    # ------------------------------------------------------------------ records (agent runs)
    def from_records(self) -> None:
        for i, record in enumerate(self.records):
            if record.kind == "hypothesis":
                self._hypothesis(record)
            elif record.kind == "tool_result" and record.observation is not None:
                self._result(i, record)

    def _hypothesis(self, record: ActivityRecord) -> None:
        args = record.args or {}
        declarations = args.get("declared")
        for raw in declarations if isinstance(declarations, list) else []:
            try:
                declared = DeclaredHypothesis.model_validate(raw)
            except ValidationError:
                continue
            # a declared hypothesis merges with the host's card for the same subject (event, data, market, ...)
            if declared.event_ref:
                key = f"event:{declared.event_ref}"
            else:
                key = declared.kind if declared.kind in _STATEMENTS else f"model:{declared.id}"
            card = self.book.get(
                key,
                declared.kind,
                declared.statement,
                subject=declared.event_ref,
                source="critic" if record.role == "skeptic" else "model",
                parent=declared.parent,
                decisive_check=declared.decisive_check,
            )
            card.source = "critic" if record.role == "skeptic" else "model"
            card.statement, card.decisive_check = declared.statement, declared.decisive_check
            card.parent = declared.parent
            self.book.alias[f"model:{declared.id}"] = card.key
        if isinstance(args.get("move"), dict):
            try:
                move = HypothesisMove.model_validate(args["move"])
            except ValidationError:
                return
            moved = self.book.find(f"model:{move.id}")
            if moved is not None:
                if move.call_id is None or any(c.call_id == move.call_id for c in moved.checks):
                    moved.status, moved.reason = move.status, move.reason
                else:
                    self.pending_moves[move.call_id] = move

    def _result(self, index: int, record: ActivityRecord) -> None:
        obs = record.observation
        assert obs is not None
        critic = _is_critic(record)
        rejected = obs.availability in ("rejected", "error", "unavailable")
        tool = obs.tool

        def check(status: HypothesisStatus | None) -> CheckRef:
            return CheckRef(
                seq=record.seq,
                call_id=obs.call_id,
                step=self.steps_by_call.get(obs.call_id),
                tool=tool,
                by="critic" if critic else "detective",
                status="rejected" if rejected else _check_status(status),
                outcome=obs.outcome,
                summary=tagged(obs.summary, [r.receipt_id for r in obs.receipt_refs]),
                receipts=list(obs.receipt_refs),
            )

        if rejected:
            if critic:
                self.critic_checks.append(check(None))
            return
        if tool == "list_events":
            events = obs.data.get("events")
            for raw in events if isinstance(events, list) else []:
                if (ref := _event_ref(raw)) is not None:
                    self.book.get(f"event:{ref[0]}", "event", f"event: {ref[1]}", subject=ref[0])
            return
        status: HypothesisStatus | None = None
        card: _Card | None = None
        if tool == "holdout_check" and (ref := _event_ref(obs.args.get("event"))) is not None:
            status = _status_of(tool, obs.outcome)
            card = self.book.get(
                f"event:{ref[0]}", "event", f"event: {ref[1]}", subject=ref[0], source="critic" if critic else "host"
            )
        elif tool in _CARD_OF_TOOL:
            kind = _CARD_OF_TOOL[tool]
            # an observed-only call (no ledger, no outcome) shows on the card but judges nothing
            status = _status_of(tool, obs.outcome) if obs.ledger is not None or obs.outcome is not None else None
            card = self.book.get(kind, kind, _STATEMENTS[kind], source="critic" if critic else "host")
        ref_check = check(status)
        if card is not None:
            self.book.judge(card, ref_check, status)
        hypothesis_id = _call_args(self.records, index).get("hypothesis_id") or obs.args.get("hypothesis_id")
        model_card = self.book.find(f"model:{hypothesis_id}") if isinstance(hypothesis_id, str) else None
        if model_card is not None and model_card is not card:
            self.book.judge(model_card, ref_check, None)
        if (move := self.pending_moves.pop(obs.call_id, None)) is not None and obs.receipt_refs:
            moved = self.book.find(f"model:{move.id}")
            if moved is not None:
                self.book.judge(moved, ref_check, move.status)
                moved.reason = move.reason
        if critic:
            self.critic_checks.append(ref_check)

    # ------------------------------------------------------------------ findings (every investigation)
    def from_findings(self) -> None:
        findings = self.findings
        if findings is None:
            return
        for step in findings.trail:
            agent = step.data.get("agent")
            call_id = agent.get("call_id") if isinstance(agent, dict) else None
            if call_id is not None and any(
                c.call_id == call_id for card in self.book.cards.values() for c in card.checks
            ):
                continue  # already on the board from its activity record
            self._step(step, call_id if isinstance(call_id, str) else None)
        for ruled in findings.ruled_out:
            ref = ruled.evidence.ref if ruled.evidence is not None else None
            card = self.book.find(f"event:{ref}") if ref else None
            if card is None:
                card = next((c for c in self.book.cards.values() if c.statement == ruled.hypothesis), None)
            status: HypothesisStatus = "ruled_out" if ruled.result == "refuted" else "inconclusive"
            if card is not None and card.checks:
                if card.status != status:
                    card.status, card.reason = status, f"{status.replace('_', ' ')}: {ruled.reason}"
                continue
            source = next((s for s in findings.trail if set(s.receipts) & set(ruled.receipts)), None)
            if card is None:
                card = (
                    self.book.get(f"event:{ref}", "event", f"event: {ruled.hypothesis}", subject=ref)
                    if ref
                    else self.book.get(f"ruled:{ruled.hypothesis}", "other", ruled.hypothesis)
                )
            check = CheckRef(
                seq=None,
                call_id=None,
                step=source.step if source is not None else None,
                tool=source.tool if source is not None else "verdict",
                by="host",
                status=_check_status(status),
                outcome=ruled.result,
                summary=tagged(ruled.reason, ruled.receipts),
                receipts=self.links(ruled.receipts),
            )
            self.book.judge(card, check, status)
            card.reason = f"{status.replace('_', ' ')}: {ruled.reason}"

    def _step(self, step: TrailStep, call_id: str | None) -> None:
        by: Literal["host", "detective", "critic"] = (
            ("critic" if ":c" in call_id else "detective") if call_id is not None else "host"
        )
        card: _Card | None = None
        status: HypothesisStatus | None = None
        outcome = _ledger_outcome(step)
        if step.kind in ("freshness", "identities"):
            card = self.book.get("data", "data", _STATEMENTS["data"])
            stopped = step.decision.startswith("stop")
            status = "supported" if stopped else "ruled_out" if step.decision == "continue" else None
            outcome = outcome or (
                ("incomplete" if stopped else "complete")
                if step.kind == "freshness"
                else ("broken" if stopped else "hold")
            )
            if card.status == "supported" and not stopped:
                status = None  # one failed data check is enough; a later passing one does not clear it
        elif step.kind == "calendar" or (step.kind == "events" and step.decision.startswith("stop: EXPECTED")):
            card = self.book.get("planned", "planned", _STATEMENTS["planned"])
            status = "supported" if step.decision.startswith("stop: EXPECTED") else "ruled_out"
            outcome = outcome or ("planned" if status == "supported" else "not planned")
        elif step.tool == "holdout_check" and (ref := _event_ref(step.data.get("event"))) is not None:
            card = self.book.get(f"event:{ref[0]}", "event", f"event: {ref[1]}", subject=ref[0])
            status = _status_of(step.tool, outcome)
        elif step.tool in _CARD_OF_TOOL and step.tool not in ("check_freshness", "check_identities"):
            kind = _CARD_OF_TOOL[step.tool]
            card = self.book.get(kind, kind, _STATEMENTS[kind])
            if step.tool == "mix_rate_split" and outcome is None:
                outcome = "mix" if "mix shift" in step.decision else "rate"
            status = _status_of(step.tool, outcome)
        if card is None:
            return
        self.book.judge(
            card,
            CheckRef(
                seq=None,
                call_id=call_id,
                step=step.step,
                tool=step.tool,
                by=by,
                status=_check_status(status),
                outcome=outcome,
                summary=tagged(step.result, step.receipts),
                receipts=self.links(step.receipts),
            ),
            status,
        )

    # ------------------------------------------------------------------ the verdict is authoritative
    def finalize(self, finished: bool) -> None:
        findings = self.findings
        cause = None
        if findings is not None and findings.verdict is Verdict.SUPPORTED_CAUSE and findings.root is not None:
            cause = findings.root.evidence.ref if findings.root.evidence is not None else None
        for card in self.book.cards.values():
            if findings is not None and card.kind == "event" and card.status == "supported" and card.subject != cause:
                card.status = "inconclusive"
                card.reason = (
                    f"consistent too, but the verdict names {cause} as the cause"
                    if cause is not None
                    else f"consistent, but the evidence admits {findings.verdict.value}, not a supported cause"
                )
            if not any(check.receipts for check in card.checks) and card.status not in ("open", "not_tested"):
                card.status, card.reason = "open", "waiting for a receipted check"
            if card.status == "open" and (finished or findings is not None):
                card.status = "not_tested"
                card.reason = "not tested before the verdict" + (
                    "" if card.kind != "event" else ": not aligned with the onset or no check left"
                )
        chosen = self.book.find(f"event:{cause}") if cause is not None else None
        if chosen is not None and any(
            c.tool == "holdout_check" and c.outcome == "consistent" and c.receipts for c in chosen.checks
        ):
            chosen.status = "supported"
            chosen.decisive_check = "holdout_check"
            chosen.reason = "supported: the holdout puts the change where this event applies; the verdict names it"

    def cards(self) -> list[HypothesisCard]:
        ids = {card.key: f"H{i}" for i, card in enumerate(self.book.cards.values(), start=1)}
        model_ids = {alias.removeprefix("model:"): key for alias, key in self.book.alias.items()}
        return [
            HypothesisCard(
                id=ids[card.key],
                parent=ids.get(model_ids.get(card.parent, "")) if card.parent else None,
                statement=card.statement,
                kind=card.kind,
                subject=card.subject,
                source=card.source,
                status=card.status,
                reason=card.reason,
                decisive_check=card.decisive_check,
                checks=card.checks,
            )
            for card in self.book.cards.values()
        ]


# ---------------------------------------------------------------------------------------------- groups


def _next_step(records: Sequence[ActivityRecord], index: int) -> ActivityRecord | None:
    """The tool result a thought or call leads to, unless the gate or the closing line comes first."""
    for record in records[index:]:
        if record.kind == "tool_result":
            return record
        if record.kind in ("gate", "run_finished", "critic", "fallback", "budget"):
            return None
    return None


def _phases(records: Sequence[ActivityRecord]) -> list[StepPhase]:
    phases: list[StepPhase] = []
    for i, record in enumerate(records):
        kind = record.kind
        phase: StepPhase
        if kind == "run_started":
            phase = "opening"
        elif kind == "hypothesis":
            phase = "hypotheses"
        elif kind == "critic":
            phase = "critic"
        elif kind in ("tool_call", "tool_result", "thought"):
            # a thought and a call belong to the check they lead to: the next result names it. A thought that
            # leads to no further call (the submission, a closing remark) belongs to the verdict.
            nxt = record if kind == "tool_result" else _next_step(records, i)
            phase = "verdict" if nxt is None else "critic" if _is_critic(nxt) else "checks"
        elif kind == "report":
            phase = "report"
        elif kind in ("action_proposed", "action_decided", "action_applied", "memory"):
            phase = "action"
        elif kind == "effect_checked":
            phase = "effect"
        elif kind in ("chat_question", "chat_answer"):
            phase = "ask"
        elif kind == "gate" and record.stage == "PROPOSE":
            phase = "action"
        else:  # gate, rejected, budget, fallback, run_finished, and any kind this reader does not know
            phase = "verdict"
        phases.append(phase)
    return phases


def _groups(
    run_id: str, records: Sequence[ActivityRecord], finished: bool, findings: Findings | None
) -> list[StepGroup]:
    phases = _phases(records)
    spans: list[tuple[StepPhase, list[ActivityRecord]]] = []
    for phase, record in zip(phases, records, strict=True):
        if spans and spans[-1][0] == phase:
            spans[-1][1].append(record)
        else:
            spans.append((phase, [record]))
    out: list[StepGroup] = []
    for n, (phase, members) in enumerate(spans, start=1):
        title, role = _TITLES[phase]
        tools = [r.tool or "?" for r in members if r.kind == "tool_result"]
        failed = any(r.kind in ("fallback", "budget") for r in members)
        last = n == len(spans)
        status: Literal["running", "done", "failed", "skipped"] = (
            "failed" if failed else "running" if last and not finished and phase != "verdict" else "done"
        )
        if phase in ("checks", "critic"):
            summary = f"{len(tools)} check(s): {', '.join(tools)}" if tools else members[-1].text
        elif phase == "opening" and findings is not None:
            opening = [s.tool for s in findings.trail if s.kind not in ("verdict", "impact") and "agent" not in s.data]
            first_agent = next((s.step for s in findings.trail if "agent" in s.data), None)
            if first_agent is not None:
                opening = [s.tool for s in findings.trail if s.step < first_agent]
            summary = f"{members[0].text}; {len(opening)} deterministic step(s) ran first: {', '.join(opening)}"
        else:
            summary = members[-1].text
        out.append(
            StepGroup(
                id=f"{run_id}:g{n}",
                title=title,
                phase=phase,
                role=role,
                first_seq=members[0].seq,
                last_seq=members[-1].seq,
                status=status,
                steps=len(members),
                tool_calls=len(tools),
                usd=round(sum(r.usd or 0.0 for r in members if r.model is not None), 6),
                summary=summary[:300],
            )
        )
    return out


# ---------------------------------------------------------------------------------------------- cost


@dataclass
class _Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0


def _usage(records: Sequence[ActivityRecord], critic_seqs: set[int]) -> dict[tuple[str, str], _Usage]:
    """Billed usage per (phase, model) from the records that carry it. A reply with several text blocks writes
    several thought records with the same usage; consecutive identical usage counts once."""
    lines: dict[tuple[str, str], _Usage] = {}
    previous: tuple[Any, ...] | None = None
    for record in records:
        if record.model is None:
            continue
        usage = (record.model, record.input_tokens, record.output_tokens, record.usd)
        if usage == previous:
            continue
        previous = usage
        line = lines.setdefault(("critic" if record.seq in critic_seqs else "detective", record.model), _Usage())
        line.calls += 1
        line.input_tokens += record.input_tokens or 0
        line.output_tokens += record.output_tokens or 0
        line.usd += record.usd or 0.0
    return lines


def _cost(
    records: Sequence[ActivityRecord],
    run: RunSummary | None,
    groups: list[StepGroup],
    has_critic: bool,
    detective_caps: tuple[float, int],
) -> CostView:
    """Totals come from the billed run (its summary, else the host's closing line), never from re-adding records:
    a call that left no record (a reply with only a tool call) still cost."""
    cap_usd, cap_calls = detective_caps
    critic_seqs = {r.seq for r in records for g in groups if g.phase == "critic" and g.first_seq <= r.seq <= g.last_seq}
    lines = _usage(records, critic_seqs)
    critic = _Usage()
    for (phase, _), line in lines.items():
        if phase == "critic":
            critic.calls += line.calls
            critic.input_tokens += line.input_tokens
            critic.output_tokens += line.output_tokens
            critic.usd += line.usd
    finished = next((r for r in records if r.kind == "run_finished"), None)
    if run is not None and run.status != "running":
        usd = run.usd
    elif finished is not None and finished.usd is not None:
        usd = finished.usd
    else:
        usd = sum(line.usd for line in lines.values())
    llm_calls = model_calls(records)
    if llm_calls is None:
        llm_calls = run.llm_calls if run is not None else sum(line.calls for line in lines.values())
    tool_calls = sum(r.kind == "tool_result" for r in records)
    if run is not None:
        tool_calls = max(tool_calls, run.tool_calls)
    out: list[CostLine] = []
    for (phase, model), line in lines.items():
        if phase == "detective":  # the detective's line takes what the billed totals hold beyond its records
            line.calls = max(line.calls, llm_calls - critic.calls)
            line.usd = max(line.usd, usd - critic.usd)
            if run is not None:
                line.input_tokens = max(line.input_tokens, run.input_tokens - critic.input_tokens)
                line.output_tokens = max(line.output_tokens, run.output_tokens - critic.output_tokens)
        out.append(
            CostLine(
                phase=cast(Literal["detective", "critic", "ask"], phase),
                model=model,
                llm_calls=line.calls,
                input_tokens=line.input_tokens,
                output_tokens=line.output_tokens,
                usd=round(line.usd, 6),
            )
        )
    return CostView(
        usd=usd,
        cap_usd=round(cap_usd + (CRITIC_CAP_USD if has_critic else 0.0), 6),
        llm_calls=llm_calls,
        tool_calls=tool_calls,
        cap_tool_calls=cap_calls + (CRITIC_CAP_TOOL_CALLS if has_critic else 0),
        replayed=run.mode == "replay" if run is not None else bool(records),
        lines=out,
    )


# ---------------------------------------------------------------------------------------------- the board


def _critic(
    records: Sequence[ActivityRecord], findings: Findings | None, checks: list[CheckRef]
) -> tuple[CriticView | None, Challenge | None]:
    challenge: Challenge | None = None
    model: str | None = None
    for record in records:
        if record.kind == "critic" and record.args:
            raw = {k: v for k, v in record.args.items() if k != "model"}
            try:
                challenge = Challenge.model_validate(raw)
            except ValidationError:
                continue
            model = record.args.get("model") if isinstance(record.args.get("model"), str) else record.model
    skeptic = findings.skeptic if findings is not None else None
    if skeptic is None and challenge is None:
        return None, None
    result = skeptic.verdict if skeptic is not None else challenge.verdict if challenge is not None else "skipped"
    attempts = len(checks) or (len(skeptic.checks) if skeptic is not None else 0)
    if challenge is not None:
        reason = challenge.reason
    elif result == "upheld":
        reason = f"{attempts} attempt(s) to falsify the cause, none succeeded"
    else:
        reason = f"the counter-check {result} the cause"
    return CriticView(result=result, model=model, attempts=attempts, reason=reason, checks=checks), challenge


def _discarded(
    records: Sequence[ActivityRecord],
    cards: list[HypothesisCard],
    run: RunSummary | None,
    critic: CriticView | None,
) -> list[Discarded]:
    out: list[Discarded] = []
    for card in cards:
        if card.status in ("ruled_out", "not_tested"):
            deciding = next((c for c in reversed(card.checks) if c.status == "refuted"), None)
            out.append(
                Discarded(
                    kind=cast(Literal["ruled_out", "not_tested"], card.status),
                    text=f"{card.statement}: {card.reason}",
                    seq=deciding.seq if deciding is not None else None,
                    receipts=deciding.receipts if deciding is not None else [],
                )
            )
    claimed_seen = False
    for record in records:
        obs = record.observation
        if record.kind == "tool_result" and obs is not None and obs.availability in ("rejected", "error"):
            out.append(Discarded(kind="rejected_call", text=f"{obs.tool}: {obs.summary}", seq=record.seq, receipts=[]))
        elif record.kind == "rejected":
            out.append(
                Discarded(kind="gate_rejection", text=record.text, seq=record.seq, receipts=record.receipt_links)
            )
        elif record.kind == "gate" and record.text.startswith("backfilled: "):
            out.append(
                Discarded(
                    kind="backfilled",
                    text=f"the model skipped it, the gate ran it: {record.text.removeprefix('backfilled: ')}",
                    seq=record.seq,
                    receipts=[],
                )
            )
        elif record.kind == "gate" and (match := _GATE.match(record.text)) and match.group(1) != match.group(2):
            claimed_seen = True
            out.append(
                Discarded(
                    kind="gate_rejection",
                    text=f"the model claimed {match.group(2)}, the evidence admits {match.group(1)}",
                    seq=record.seq,
                    receipts=[],
                )
            )
    gate = run.gate if run is not None else None
    if not claimed_seen and gate is not None and gate.claimed != "none" and gate.claimed != gate.admitted:
        out.append(
            Discarded(
                kind="gate_rejection",
                text=f"the model claimed {gate.claimed}, the evidence admits {gate.admitted}",
                seq=None,
                receipts=[],
            )
        )
    if critic is not None and critic.result in ("weakened", "refuted"):
        deciding = next((c for c in critic.checks if c.status == "refuted"), None)
        out.append(
            Discarded(
                kind="critic_downgrade",
                text=f"the counter-check {critic.result} the cause: {critic.reason}",
                seq=deciding.seq if deciding is not None else None,
                receipts=deciding.receipts if deciding is not None else [],
            )
        )
    return out


def _precedents(records: Sequence[ActivityRecord], given: Sequence[Precedent]) -> list[Precedent]:
    out = list(given)
    for record in records:
        if record.kind == "memory" and record.args:
            try:
                precedent = Precedent.model_validate(record.args)
            except ValidationError:
                continue
            if precedent not in out:
                out.append(precedent)
    return out


def build_board(
    records: Sequence[ActivityRecord],
    findings: Findings | None,
    run: RunSummary | None,
    precedents: Sequence[Precedent] = (),
    *,
    incident: Incident | None = None,
    profile: Literal["stage2", "v1", "v2"] | None = None,
    labels: Mapping[str, str] | None = None,
    run_id: str | None = None,
    detective_caps: tuple[float, int] = DETECTIVE_CAPS,
) -> Board:
    """The board of one investigation from what is visible now.

    `records` may hold the whole journal: only the run's own are read (`run_id`, else `run.run_id`, else the
    run named in the findings' trail; none of them: a Stage-2-only board). Ask runs never count."""
    if incident is not None and findings is None:
        findings = incident.findings
    run_id = run_id or (run.run_id if run is not None else _run_id_of(findings))
    mine = [r for r in records if run_id is not None and r.run_id == run_id and r.stage != "ASK"]
    revision = revision_of(run_id, mine)
    finished = any(r.kind == "run_finished" for r in mine) or (run is not None and run.status != "running")

    derivation = _Derivation(mine, findings, run_id, revision)
    derivation.from_records()
    derivation.from_findings()
    derivation.finalize(finished)
    cards = derivation.cards()
    counts: dict[HypothesisStatus, int] = dict.fromkeys(HYPOTHESIS_STATUSES, 0)
    for card in cards:
        counts[card.status] += 1

    groups = _groups(run_id, mine, finished, findings) if run_id is not None and mine else []
    critic, _ = _critic(mine, findings, derivation.critic_checks)
    has_critic = critic is not None or bool(derivation.critic_checks)
    if profile is None:
        v2 = has_critic or any(r.kind in V2_KINDS for r in mine)
        profile = "stage2" if not mine else "v2" if v2 else "v1"

    state: Literal["running", "done", "fallback", "budget"] = "done"
    if any(r.kind == "budget" for r in mine) or (run is not None and run.status == "budget"):
        state = "budget"
    elif any(r.kind == "fallback" for r in mine) or (run is not None and run.status == "fallback"):
        state = "fallback"
    elif mine and not finished and findings is None:
        state = "running"

    incident_id = (
        (incident.id if incident is not None else None)
        or (findings.incident_id if findings is not None else None)
        or next((r.incident_id for r in mine if r.incident_id), None)
    )
    anomaly_id = (
        (findings.anomaly_id if findings is not None else None)
        or (run.anomaly_id if run is not None else None)
        or next((r.anomaly_id for r in mine if r.anomaly_id), None)
    )
    chain = (
        chain_of(
            findings,
            incident_id,
            symptoms=incident.symptoms if incident is not None else (),
            run_id=run_id,
            world_revision=revision,
            labels=labels,
        )
        if findings is not None and incident_id is not None
        else None
    )
    return Board(
        version=BOARD_VERSION,
        agent_run=run_id if mine else None,
        incident_id=incident_id,
        anomaly_id=anomaly_id,
        through_seq=mine[-1].seq if mine else 0,
        state=state,
        profile=profile,
        hypotheses=cards,
        counts=counts,
        groups=groups,
        discarded=_discarded(mine, cards, run, critic),
        chain=chain,
        critic=critic,
        precedents=_precedents(mine, precedents),
        second_opinion=None,
        cost=_cost(mine, run, groups, has_critic, detective_caps),
    )


def build_boards(
    records: Sequence[ActivityRecord],
    incidents: Sequence[Incident],
    runs: Mapping[str, RunSummary] | Sequence[RunSummary] = (),
    *,
    labels: Mapping[str, str] | None = None,
    profile: ProfileName | None = None,
    detective_caps: tuple[float, int] = DETECTIVE_CAPS,
) -> list[Board]:
    """One board per agent investigation in `records`, joined with its incident when that is visible."""
    summaries = {r.run_id: r for r in (runs.values() if isinstance(runs, Mapping) else runs)}
    boards: list[Board] = []
    for record in records:
        if record.kind != "run_started" or record.stage == "ASK" or record.run_id is None:
            continue
        incident = incident_of(record.run_id, record.anomaly_id, incidents)
        boards.append(
            build_board(
                records,
                None,
                summaries.get(record.run_id),
                incident=incident,
                labels=labels,
                run_id=record.run_id,
                profile=profile,
                detective_caps=detective_caps,
            )
        )
    return boards


def incident_of(run_id: str, anomaly_id: str | None, incidents: Sequence[Incident]) -> Incident | None:
    by_run = next((i for i in incidents if _run_id_of(i.findings) == run_id), None)
    if by_run is not None:
        return by_run
    return next((i for i in incidents if anomaly_id is not None and i.findings.anomaly_id == anomaly_id), None)


def run_of(incident: Incident, records: Sequence[ActivityRecord]) -> str | None:
    """The agent investigation behind an incident, if any (by the trail's agent tag, else by its anomaly)."""
    run_id = _run_id_of(incident.findings)
    if run_id is not None:
        return run_id
    return next(
        (
            r.run_id
            for r in records
            if r.kind == "run_started" and r.stage != "ASK" and r.anomaly_id == incident.findings.anomaly_id
        ),
        None,
    )


__all__ = ["build_board", "build_boards", "model_calls", "revision_of", "run_of"]
