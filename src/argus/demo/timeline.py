"""Adapt an existing runtime recording to the demo's presentation timeline."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from itertools import pairwise
from typing import Any

from argus.api.digest import Digest, build_digest
from argus.api.recording import FIXTURES, Recording, load_recording
from argus.api.state import RunState
from argus.contracts.events import Event, EventType, InvestigationStepPayload, TickPayload
from argus.contracts.findings import Anomaly, Incident, Receipt
from argus.contracts.graph import Graph
from argus.demo.contracts import (
    AnomalyAppears,
    AttentionShifts,
    BeatData,
    BeatKind,
    Cue,
    Evidence,
    InvestigationSteps,
    MorningReport,
    QuietWorld,
    Scenario,
    VerdictBeat,
)

DURATION_MS = 90_000
_BEATS: tuple[tuple[int, BeatKind, str], ...] = (
    (0, "quiet_world", "Quiet world"),
    (12_000, "anomaly_appears", "Anomaly appears"),
    (21_000, "attention_shifts", "Attention shifts"),
    (30_000, "investigation_steps", "Check data and calendar"),
    (40_000, "investigation_steps", "Follow the metric graph"),
    (50_000, "investigation_steps", "Test candidate explanations"),
    (60_000, "evidence", "Evidence"),
    (72_000, "verdict", "Verdict"),
    (82_000, "morning_report", "Morning report"),
)
OFFSETS = tuple(at_ms for at_ms, _, _ in _BEATS)


@dataclass(frozen=True)
class Timeline:
    scenario: Scenario
    cues: tuple[Cue, ...]
    graph: Graph
    receipts: dict[str, Receipt]
    receipt_beats: dict[str, int]


def _receipt_ids(data: Any) -> Iterator[str]:
    """Find C3/C4/C5 receipt-reference fields, including those in structured trail results."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "receipt" and isinstance(value, str):
                yield value
            elif key == "receipts" and isinstance(value, list):
                yield from (item for item in value if isinstance(item, str))
            yield from _receipt_ids(value)
    elif isinstance(data, list):
        for item in data:
            yield from _receipt_ids(item)


def _morning_digest(recording: Recording, incident: Incident, anomaly: Anomaly) -> tuple[Event, Digest]:
    ticks = [event for event in recording.events if event.type is EventType.TICK]
    morning = next(
        (
            tick
            for tick in ticks
            if (hour := TickPayload.model_validate(tick.payload).hour) > anomaly.hour and hour.hour == 8
        ),
        ticks[-1],
    )
    state = RunState(recording.graph)
    for event in recording.events:
        if event.sim_ts > morning.sim_ts:
            break
        state.apply(event)
    snapshot = next(
        snap.incident
        for snap in reversed(recording.incidents)
        if snap.seq <= state.last_seq and snap.incident.id == incident.id
    )
    return morning, build_digest(state, [snapshot], state.current_graph())


def _steps_by_kind(recording: Recording, anomaly_id: str) -> dict[str, list[Event]]:
    groups: dict[str, list[Event]] = {}
    for event in recording.events:
        if event.type is EventType.INVESTIGATION_STEP:
            payload = InvestigationStepPayload.model_validate(event.payload)
            if payload.anomaly_id == anomaly_id:
                groups.setdefault(payload.step.kind, []).append(event)
    return groups


def _build_timeline(scenario: Scenario, recording: Recording) -> Timeline:
    # The first completed investigation anchors the script, independent of its seq in the file.
    incident = recording.incidents[0].incident
    anomaly_event = next(
        event
        for event in recording.events
        if event.type is EventType.ANOMALY_OPENED and event.payload["id"] == incident.findings.anomaly_id
    )
    anomaly = Anomaly.model_validate(anomaly_event.payload)
    quiet_ticks = [
        event for event in recording.events if event.type is EventType.TICK and event.sim_ts < anomaly_event.sim_ts
    ]
    attention = next(
        (
            event
            for event in recording.events
            if event.type is EventType.ATTENTION and event.sim_ts == anomaly_event.sim_ts
        ),
        None,
    )
    groups = _steps_by_kind(recording, anomaly.id)

    def steps(*kinds: str) -> list[Event]:
        return sorted((event for kind in kinds for event in groups.get(kind, [])), key=lambda event: event.seq)

    opening = steps("freshness", "identities", "calendar")
    localize = steps("decompose", "segment")
    hypotheses = steps("events")
    evidence = steps("holdout", "impact")
    verdict = groups["verdict"][-1]
    morning, digest = _morning_digest(recording, incident, anomaly)
    content: Sequence[tuple[Event, BeatData]] = (
        (quiet_ticks[-1], QuietWorld(tick=quiet_ticks[-1], quiet_hours=len(quiet_ticks))),
        (anomaly_event, AnomalyAppears(anomaly=anomaly_event)),
        (attention or anomaly_event, AttentionShifts(metric=anomaly.node, attention=attention)),
        (opening[0], InvestigationSteps(phase="opening", steps=opening)),
        (localize[0], InvestigationSteps(phase="localize", steps=localize)),
        (hypotheses[0], InvestigationSteps(phase="hypotheses", steps=hypotheses)),
        (evidence[0], Evidence(steps=evidence)),
        (
            verdict,
            VerdictBeat(
                outcome=incident.verdict, decision=verdict, calendar_check=groups["calendar"][0], incident=incident
            ),
        ),
        (morning, MorningReport(digest=digest)),
    )
    cues = tuple(
        Cue(
            index=index,
            kind=kind,
            title=title,
            at_ms=at_ms,
            duration_ms=until_ms - at_ms,
            sim_ts=event.sim_ts,
            data=data,
        )
        for index, ((at_ms, kind, title), (_, until_ms), (event, data)) in enumerate(
            zip(_BEATS, pairwise((*OFFSETS, DURATION_MS)), content, strict=True)
        )
    )
    receipt_beats = dict.fromkeys(_receipt_ids(recording.graph.model_dump()), 0)
    for cue in cues:
        for receipt in _receipt_ids(cue.data.model_dump()):
            receipt_beats.setdefault(receipt, cue.index)
    return Timeline(
        scenario, cues, recording.graph, {receipt.id: receipt for receipt in recording.receipts}, receipt_beats
    )


@cache
def load_timeline(scenario: Scenario) -> Timeline:
    """Use the built-in seed 1 recordings regardless of the server's regular live/replay source."""
    path = FIXTURES if scenario == "s1" else FIXTURES / scenario
    try:
        return _build_timeline(scenario, load_recording(path))
    except (IndexError, KeyError, StopIteration) as exc:
        raise ValueError(f"{scenario} recording is missing a required demo cue") from exc
