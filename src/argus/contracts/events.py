"""C5 event stream and REST API.

The runtime publishes every step as an `Event` on an in-process bus.
The API streams them as Server-Sent Events on `GET /events`:

```
id: 42
event: investigation_step
data: {"seq": 42, "type": "investigation_step", "sim_ts": "2026-11-20T14:00:00", "payload": {...}}
```

`payload` is validated against the model registered for its `type` in `PAYLOAD_MODELS`.
Types marked "reserved" are part of the contract but not emitted yet; their owner lane adds them.
The UI has a replay mode that plays `fixtures/events.jsonl` through the same code path as live.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from argus.contracts.findings import (
    Anomaly,
    Direction,
    IncidentState,
    Note,
    Segment,
    TableFreshness,
    TrailStep,
    Verdict,
)
from argus.contracts.graph import EdgeStatus, EdgeTestResult, GraphChange


class EventType(StrEnum):
    TICK = "tick"
    ATTENTION = "attention"
    EDGE_STATUS = "edge_status"
    ANOMALY_OPENED = "anomaly_opened"
    INVESTIGATION_STEP = "investigation_step"
    SKEPTIC_STEP = "skeptic_step"
    INCIDENT_UPDATED = "incident_updated"
    NOTE_LOGGED = "note_logged"
    GRAPH_CHANGED = "graph_changed"
    BENCH_PROGRESS = "bench_progress"
    CHALLENGE_STATE = "challenge_state"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TickPayload(_Strict):
    as_of: datetime
    hour: datetime = Field(description="data hour scored in this tick (as_of minus the delivery lag)")
    freshness: list[TableFreshness]
    scored_nodes: list[str]
    pending_nodes: list[str] = Field(default_factory=list, description="not scored: source data incomplete")
    max_abs_z: dict[str, float] = Field(default_factory=dict, description="node -> |z| of this hour")
    open_incidents: int


class AttentionPayload(_Strict):
    """Reserved (lane B): attention = business_weight x surprise x data_confidence x novelty."""

    scores: dict[str, float]


class EdgeStatusPayload(_Strict):
    edge: str
    old_status: EdgeStatus | None
    new_status: EdgeStatus
    result: EdgeTestResult


class InvestigationStepPayload(_Strict):
    anomaly_id: str
    incident_id: str | None = None
    step: TrailStep


class SkepticStepPayload(_Strict):
    """Reserved (lane B): one refutation check of the skeptic."""

    incident_id: str
    check: str
    result: str
    receipts: list[str] = Field(default_factory=list)


class IncidentUpdatedPayload(_Strict):
    """Summary for the feed; the full incident with findings is at GET /incidents/{id}."""

    id: str
    title: str
    state: IncidentState
    verdict: Verdict
    root_node: str
    segment: Segment
    direction: Direction
    severity_eur: float
    change: Literal["opened", "updated", "state", "reopened"]
    reason: str = ""


class BenchProgressPayload(_Strict):
    """Reserved (lane W): progress of a bench run."""

    run_id: str
    done: int
    total: int
    last: dict[str, Any] = Field(default_factory=dict)


class ChallengeStatePayload(_Strict):
    """Reserved (lane W): blind challenge state (committed hash, then reveal)."""

    state: Literal["committed", "running", "revealed"]
    commitment: str
    reveal: dict[str, Any] | None = None


PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.TICK: TickPayload,
    EventType.ATTENTION: AttentionPayload,
    EventType.EDGE_STATUS: EdgeStatusPayload,
    EventType.ANOMALY_OPENED: Anomaly,
    EventType.INVESTIGATION_STEP: InvestigationStepPayload,
    EventType.SKEPTIC_STEP: SkepticStepPayload,
    EventType.INCIDENT_UPDATED: IncidentUpdatedPayload,
    EventType.NOTE_LOGGED: Note,
    EventType.GRAPH_CHANGED: GraphChange,
    EventType.BENCH_PROGRESS: BenchProgressPayload,
    EventType.CHALLENGE_STATE: ChallengeStatePayload,
}

RESERVED_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.ATTENTION,
        EventType.SKEPTIC_STEP,
        EventType.GRAPH_CHANGED,
        EventType.BENCH_PROGRESS,
        EventType.CHALLENGE_STATE,
    }
)


class Event(_Strict):
    seq: int = Field(description="monotonic within one stream, also the SSE id")
    type: EventType
    sim_ts: datetime = Field(description="simulated wall clock (as_of) when the event happened")
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Event:
        PAYLOAD_MODELS[self.type].model_validate(self.payload)
        return self

    @classmethod
    def make(cls, seq: int, sim_ts: datetime, payload: BaseModel) -> Event:
        for event_type, model in PAYLOAD_MODELS.items():
            if type(payload) is model:
                return cls(seq=seq, type=event_type, sim_ts=sim_ts, payload=payload.model_dump(mode="json"))
        raise TypeError(f"no event type for payload {type(payload).__name__}")


class Route(_Strict):
    method: Literal["GET", "POST"]
    path: str
    summary: str
    owner: Literal["U", "W", "G", "B"]
    status: Literal["implemented", "stub"]


ROUTES: tuple[Route, ...] = (
    Route(method="GET", path="/health", summary="liveness and run mode", owner="U", status="implemented"),
    Route(method="GET", path="/events", summary="SSE stream of Event", owner="U", status="implemented"),
    Route(method="GET", path="/graph", summary="current Graph (C3)", owner="G", status="implemented"),
    Route(method="GET", path="/incidents", summary="all incidents, newest first", owner="B", status="implemented"),
    Route(
        method="GET",
        path="/incidents/{id}",
        summary="incident with findings and trail",
        owner="B",
        status="implemented",
    ),
    Route(
        method="GET",
        path="/incidents/{id}/report",
        summary="rendered report (markdown)",
        owner="U",
        status="implemented",
    ),
    Route(
        method="GET", path="/notes", summary="'didn't wake you' and data-issue notes", owner="B", status="implemented"
    ),
    Route(method="GET", path="/receipts/{id}", summary="one receipt", owner="G", status="implemented"),
    Route(
        method="POST",
        path="/receipts/{id}/rerun",
        summary="re-run the SQL at its as_of, compare hash",
        owner="G",
        status="implemented",
    ),
    Route(method="POST", path="/metrics", summary="onboard a metric YAML (C2)", owner="G", status="stub"),
    Route(
        method="POST", path="/chaos/inject", summary="inject a scenario into the live world", owner="W", status="stub"
    ),
    Route(method="POST", path="/challenge/commit", summary="blind challenge: commit", owner="W", status="stub"),
    Route(method="POST", path="/challenge/reveal", summary="blind challenge: reveal", owner="W", status="stub"),
    Route(method="GET", path="/bench/results", summary="latest bench scorecard", owner="W", status="stub"),
    Route(
        method="POST",
        path="/incidents/{id}/feedback",
        summary="approve, dismiss or 'wrong cause'",
        owner="B",
        status="stub",
    ),
)
