"""Versioned wire models for the demo endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.api.digest import Digest
from argus.contracts.events import Event
from argus.contracts.findings import Incident, Verdict

type Scenario = Literal["s1", "s4"]
type Variant = Literal["legacy", "agent"]
type Action = Literal["pause", "resume", "skip", "restart"]
type Decision = Literal["approve", "deny"]
type Status = Literal["idle", "playing", "paused", "awaiting_approval", "completed"]
type BeatKind = Literal[
    "quiet_world",
    "anomaly_appears",
    "attention_shifts",
    "investigation_steps",
    "evidence",
    "verdict",
    "agent_activity",
    "agent_verdict",
    "action_proposed",
    "action_executed",
    "effect_checked",
    "morning_report",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartDemo(_Strict):
    scenario: Scenario = "s4"
    speed: float = Field(default=1.0, ge=0.25, le=100, allow_inf_nan=False)
    variant: Variant = "legacy"


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


class AgentDemoState(DemoState):
    variant: Literal["agent"] = "agent"
    decision: Decision | None = None
    sim_ts: datetime
    through_seq: int


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
    counterfactual: str = Field(description="GET path of the incident's counterfactual replay for this demo run")


class MorningReport(_Strict):
    digest: Digest
    report: str = Field(description="GET path of the narrator's morning report for this demo run")


class RecordingPrefix(_Strict):
    through_seq: int = Field(ge=0, description="last visible C5 event sequence")


type BeatData = (
    QuietWorld
    | AnomalyAppears
    | AttentionShifts
    | InvestigationSteps
    | Evidence
    | VerdictBeat
    | MorningReport
    | RecordingPrefix
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
