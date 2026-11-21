"""Versioned wire models for the demo endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.api.digest import Digest
from argus.contracts.events import Event
from argus.contracts.findings import Incident, Verdict

type Scenario = Literal["s1", "s4"]
type Action = Literal["pause", "resume", "skip", "restart"]
type Status = Literal["idle", "playing", "paused", "completed"]
type BeatKind = Literal[
    "quiet_world",
    "anomaly_appears",
    "attention_shifts",
    "investigation_steps",
    "evidence",
    "verdict",
    "morning_report",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartDemo(_Strict):
    scenario: Scenario = "s4"
    speed: float = Field(default=1.0, ge=0.25, le=100, allow_inf_nan=False)


class ControlDemo(_Strict):
    action: Action


class DemoState(_Strict):
    version: Literal[1] = 1
    run_id: str | None = None
    scenario: Scenario | None = None
    status: Status = "idle"
    speed: float | None = None
    elapsed_ms: int = 0
    duration_ms: int | None = None
    beat_index: int | None = None
    beat_count: int = 0


class QuietWorld(_Strict):
    tick: Event
    quiet_hours: int


class AnomalyAppears(_Strict):
    anomaly: Event


class AttentionShifts(_Strict):
    metric: str
    attention: Event | None


class InvestigationSteps(_Strict):
    phase: Literal["opening", "localize", "hypotheses"]
    steps: list[Event]


class Evidence(_Strict):
    steps: list[Event]


class VerdictBeat(_Strict):
    outcome: Verdict
    decision: Event
    calendar_check: Event
    incident: Incident


class MorningReport(_Strict):
    digest: Digest


type BeatData = (
    QuietWorld | AnomalyAppears | AttentionShifts | InvestigationSteps | Evidence | VerdictBeat | MorningReport
)


class Cue(_Strict):
    index: int
    kind: BeatKind
    title: str
    at_ms: int
    duration_ms: int
    sim_ts: datetime
    data: BeatData


class DemoBeat(Cue):
    version: Literal[1] = 1
    run_id: str
    scenario: Scenario
