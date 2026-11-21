"""Presentation cues and read-only views of a sealed agent run."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path

from pydantic import BaseModel

from argus.agent.types import ActivityRecord, ProposalView
from argus.api.digest import build_digest
from argus.api.recording import FIXTURES, IncidentSnapshot, Recording
from argus.api.state import RunState
from argus.contracts.events import Event, EventType, TickPayload
from argus.contracts.findings import Incident
from argus.contracts.graph import Graph
from argus.demo.bundle import AgentBundle, AskAnswer, ReceiptProof, RecordedAsk, read_bundle, receipt_keys
from argus.demo.contracts import AgentDemoState, BeatKind, Cue, MorningReport, RecordingPrefix, Scenario
from argus.demo.timeline import DURATION_MS, REPORT_PATH, DemoReport, build_report
from argus.narrator.morning import AgentMorning


@dataclass(frozen=True)
class AgentTimeline:
    bundle: AgentBundle
    cues: tuple[Cue, ...]
    offsets: tuple[int, ...]
    activity_cursors: tuple[int, ...]
    approval_index: int | None
    effect_index: int | None
    report: DemoReport | None

    @property
    def scenario(self) -> Scenario:
        return self.bundle.manifest.scenario

    @property
    def graph(self) -> Graph:
        return self.bundle.graph

    def through_seq(self, index: int) -> int:
        data = self.cues[index].data
        if isinstance(data, RecordingPrefix):
            return data.through_seq
        assert self.report is not None
        return self.report.window.through_seq

    def view(self, state: AgentDemoState) -> AgentView:
        assert state.beat_index is not None
        index = state.beat_index
        prefix = self.bundle.prefix
        branch = self.bundle.continuation(state.decision)
        parts = (prefix,) if branch is None else (prefix, branch)
        events = tuple(event for part in parts for event in part.events if event.seq <= state.through_seq)
        cursor = self.activity_cursors[index]
        include_decision = branch is not None
        activity = tuple(
            record
            for part in parts
            for record in part.activity
            if record.sim_ts <= state.sim_ts
            and (record.seq <= cursor or (include_decision and record.kind == "action_decided"))
        )
        actions: list[ProposalView] = []
        if self.approval_index is not None and index >= self.approval_index:
            for proposal in prefix.actions.values():
                recorded = branch.actions.get(proposal.id) if branch else None
                if recorded is None:
                    actions.append(proposal)
                elif state.decision == "deny" or (self.effect_index is not None and index >= self.effect_index):
                    actions.append(recorded)
                else:
                    applied = any(r.kind == "action_applied" and r.action_id == proposal.id for r in activity)
                    actions.append(
                        proposal.model_copy(
                            update={"state": "APPLIED" if applied else "APPLYING", "decision": recorded.decision}
                        )
                    )

        incidents = {
            incident.id: incident
            for part in parts
            if not part.events or part.events[-1].seq <= state.through_seq
            for incident in part.incidents
            if incident.updated_at <= state.sim_ts
        }
        questions = tuple(q for part in parts for q in part.questions if q.through_seq <= state.through_seq)
        refs: list[BaseModel] = [self.graph, *events, *activity, *actions, *incidents.values()]
        receipts = {key: proof for part in parts for key, proof in part.receipts.items()}
        # A recorded answer can be taken only when all of its evidence exists at this clock position.
        questions = tuple(
            question
            for question in questions
            if all(receipts[key].receipt.as_of <= state.sim_ts for key in _links(question))
        )
        keys = {key for model in (*refs, *questions) for key in _links(model)}
        visible = {key: receipts[key] for key in keys if receipts[key].receipt.as_of <= state.sim_ts}
        return AgentView(state, events, activity, actions, list(incidents.values()), visible, questions)


def _links(model: BaseModel) -> set[str]:
    return set(receipt_keys(model.model_dump(mode="json")))


def _question_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).rstrip("?! .")


@dataclass(frozen=True)
class AgentView:
    state: AgentDemoState
    events: tuple[Event, ...]
    activity: tuple[ActivityRecord, ...]
    actions: list[ProposalView]
    incidents: list[Incident]
    receipts: dict[str, ReceiptProof]
    questions: tuple[RecordedAsk, ...]

    def ask(self, question: str, incident_id: str | None = None) -> AskAnswer:
        if incident_id is None or any(incident.id == incident_id for incident in self.incidents):
            key = _question_key(question)
            matching = [item for item in self.questions if _question_key(item.question) == key]
            if matching:
                return max(matching, key=lambda item: item.through_seq).response
        return AskAnswer(
            status="unavailable",
            answer="This recording has no answer to that question at the current demo time.",
            claims=[],
            receipt_links=[],
            activity_cursor=self.activity[-1].seq if self.activity else 0,
        )


@dataclass(frozen=True)
class _Mark:
    at_ms: int
    kind: BeatKind
    title: str
    sim_ts: datetime
    through_seq: int
    activity_cursor: int


def _build_timeline(bundle: AgentBundle) -> AgentTimeline:
    prefix = bundle.prefix
    try:
        incident = prefix.incidents[0]
        anomaly = next(
            event
            for event in prefix.events
            if event.type is EventType.ANOMALY_OPENED and event.payload["id"] == incident.findings.anomaly_id
        )
        quiet = [e for e in prefix.events if e.type is EventType.TICK and e.sim_ts < anomaly.sim_ts][-1]
        first_tool = next(r for r in prefix.activity if r.kind == "tool_call" and r.sim_ts >= anomaly.sim_ts)
        result = next(r for r in prefix.activity if r.kind == "tool_result" and r.seq > first_tool.seq)
        last = prefix.events[-1]
        presented_at = max(last.sim_ts, prefix.activity[-1].sim_ts)
        action_index = effect_index = None
        approve = bundle.approve
        deny = bundle.deny
        proposed = next((r for r in prefix.activity if r.kind == "action_proposed"), None)
        before_proposal = proposed.seq - 1 if proposed else prefix.activity[-1].seq
        marks = [
            _Mark(0, "quiet_world", "Quiet world", quiet.sim_ts, quiet.seq, _cursor(prefix.activity, quiet.sim_ts)),
            _Mark(12_000, "anomaly_appears", "Anomaly appears", anomaly.sim_ts, anomaly.seq, first_tool.seq - 1),
            _Mark(20_000, "agent_activity", "Argus chooses a check", first_tool.sim_ts, anomaly.seq, first_tool.seq),
            _Mark(28_000, "agent_activity", "Argus receives evidence", result.sim_ts, anomaly.seq, result.seq),
            _Mark(34_000, "agent_verdict", "Evidence and verdict", presented_at, last.seq, before_proposal),
        ]
        report: DemoReport | None = None
        morning_data: MorningReport | None = None
        if approve is not None and deny is not None:
            if (
                proposed is None
                or proposed is not prefix.activity[-1]
                or proposed.sim_ts != presented_at
                or not proposed.action_id
                or any(
                    record.kind in {"action_decided", "action_applied", "effect_checked"} for record in prefix.activity
                )
            ):
                raise ValueError("the S4 presentation prefix must end at its proposal hour")
            if set(prefix.actions) != {proposed.action_id}:
                raise ValueError("the S4 presentation requires one pending action")
            pending = prefix.actions[proposed.action_id]
            approved, denied = approve.actions[pending.id], deny.actions[pending.id]
            _check_decisions(pending, approved, denied, proposed.sim_ts)
            for continuation in (approve, deny):
                decision = continuation.activity[0]
                if (
                    decision.kind != "action_decided"
                    or decision.actor != "operator"
                    or decision.action_id != pending.id
                    or decision.sim_ts != proposed.sim_ts
                ):
                    raise ValueError("continuation must start with the matching operator decision")
            if any(r.kind in {"action_applied", "effect_checked"} for r in deny.activity):
                raise ValueError("denial continuation contains execution or effect evidence")
            applied = next(r for r in approve.activity if r.kind == "action_applied" and r.action_id == pending.id)
            if sum(r.kind == "action_applied" for r in approve.activity) != 1:
                raise ValueError("approval must apply the recorded rollback exactly once")
            assert approved.effect is not None
            checked = next(
                r
                for r in approve.activity
                if r.kind == "effect_checked" and r.action_id == pending.id and r.sim_ts == approved.effect.checked_at
            )
            if checked.seq <= applied.seq:
                raise ValueError("the final action must have an effect matching the recorded check")
            if (
                approved.effect.state == "VERIFIED"
                and len(set(link.key() for link in approved.effect.receipt_refs)) < 2
            ):
                raise ValueError("verified effect requires treated and untouched evidence")
            events = prefix.events + approve.events
            morning = next(
                event
                for event in approve.events
                if event.type is EventType.TICK
                and event.sim_ts > checked.sim_ts
                and TickPayload.model_validate(event.payload).hour.hour == 8
            )
            report, morning_data = _morning(bundle, events, morning)
            action_index = len(marks)
            effect_index = action_index + 2
            marks.extend(
                (
                    _Mark(
                        50_000,
                        "action_proposed",
                        "Awaiting approval",
                        proposed.sim_ts,
                        last.seq,
                        prefix.activity[-1].seq,
                    ),
                    _Mark(
                        70_000,
                        "action_executed",
                        "Rollback applied",
                        applied.sim_ts,
                        _seq(events, applied.sim_ts),
                        applied.seq,
                    ),
                    _Mark(
                        80_000,
                        "effect_checked",
                        "Effect checked",
                        checked.sim_ts,
                        _seq(events, checked.sim_ts),
                        checked.seq,
                    ),
                    _Mark(
                        86_000,
                        "morning_report",
                        "Morning report",
                        morning.sim_ts,
                        report.window.through_seq,
                        _cursor(prefix.activity + approve.activity, morning.sim_ts),
                    ),
                )
            )
    except (IndexError, KeyError, StopIteration) as exc:
        raise ValueError("agent recording is missing a required presentation milestone") from exc
    if any(
        a.sim_ts > b.sim_ts or a.through_seq > b.through_seq or a.activity_cursor > b.activity_cursor
        for a, b in pairwise(marks)
    ):
        raise ValueError("agent presentation milestones move backwards")
    offsets = tuple(mark.at_ms for mark in marks)
    cues = tuple(
        Cue(
            index=index,
            kind=mark.kind,
            title=mark.title,
            at_ms=at_ms,
            duration_ms=next_ms - at_ms,
            sim_ts=mark.sim_ts,
            data=morning_data
            if mark.kind == "morning_report" and morning_data
            else RecordingPrefix(through_seq=mark.through_seq),
        )
        for index, (mark, (at_ms, next_ms)) in enumerate(zip(marks, pairwise((*offsets, DURATION_MS)), strict=True))
    )
    return AgentTimeline(
        bundle, cues, offsets, tuple(mark.activity_cursor for mark in marks), action_index, effect_index, report
    )


def _check_decisions(pending: ProposalView, approved: ProposalView, denied: ProposalView, at: datetime) -> None:
    if pending.state != "AWAIT_OPERATOR" or pending.decision or pending.effect:
        raise ValueError("the common prefix must contain a pending proposal")
    for branch, decision in ((approved, "approve"), (denied, "deny")):
        if branch.model_dump(exclude={"state", "decision", "effect"}) != pending.model_dump(
            exclude={"state", "decision", "effect"}
        ):
            raise ValueError("the continuation changes the approved proposal")
        if branch.decision is None or branch.decision.decision != decision or branch.decision.at != at:
            raise ValueError("the recorded decision must match the proposal hour and branch")
    if (
        denied.state != "DENIED"
        or denied.effect is not None
        or approved.effect is None
        or approved.state != approved.effect.state
    ):
        raise ValueError("the action continuations must end in a denial or measured effect")


def _seq(events: tuple[Event, ...], at: datetime) -> int:
    return max((event.seq for event in events if event.sim_ts <= at), default=0)


def _cursor(activity: tuple[ActivityRecord, ...], at: datetime) -> int:
    return max((record.seq for record in activity if record.sim_ts <= at), default=0)


def _morning(bundle: AgentBundle, events: tuple[Event, ...], morning: Event) -> tuple[DemoReport, MorningReport]:
    assert bundle.approve is not None
    through = _seq(events, morning.sim_ts)
    incidents = {
        incident.id: incident
        for part in (bundle.prefix, bundle.approve)
        for incident in part.incidents
        if incident.updated_at <= morning.sim_ts
    }
    state = RunState(bundle.graph)
    for event in events:
        if event.seq > through:
            break
        state.apply(event)
    graph = state.current_graph()
    recording = Recording(
        list(events),
        graph,
        [IncidentSnapshot(seq=through, incident=incident) for incident in incidents.values()],
        [
            proof.receipt
            for part in (bundle.prefix, bundle.approve)
            for key, proof in part.receipts.items()
            if "/" not in key and proof.receipt.as_of <= morning.sim_ts
        ],
    )
    final_actions = tuple(bundle.approve.actions.values())
    report = build_report(
        f"demo-agent-{bundle.manifest.bundle_sha[:16]}",
        recording,
        morning,
        agent_projection=lambda _: AgentMorning(actions=final_actions),
    )
    return report, MorningReport(digest=build_digest(state, list(incidents.values()), graph), report=REPORT_PATH)


def load_agent_timeline(scenario: Scenario) -> AgentTimeline:
    path = Path(os.environ.get("ARGUS_DEMO_BUNDLE", str(FIXTURES / "agent" / "v1" / scenario)))
    expected_sha = os.environ.get("ARGUS_DEMO_BUNDLE_SHA")
    if not expected_sha:
        raise ValueError("configure ARGUS_DEMO_BUNDLE_SHA with the sealed recording digest")
    return _build_timeline(read_bundle(path, scenario, expected_sha))
