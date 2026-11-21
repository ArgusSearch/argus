"""C6 tools: the typed checks the investigator, the skeptic, the LLM planner and the MCP server may run.

No tool accepts free SQL. Every tool returns a result plus the receipts of the queries it ran.
The LLM planner (lane B, Stage 2) may only pick a tool from `TOOLS` and fill its input model;
deterministic code runs the tool and decides validated / refuted / inconclusive.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.findings import Contribution, EvidenceRef, Segment, TableFreshness, Window


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolOutput(_Strict):
    summary: str
    receipts: list[str] = Field(default_factory=list)


class GetSeriesInput(_Strict):
    node: str
    segment: Segment = Field(default_factory=dict)
    window: Window


class SeriesPoint(_Strict):
    hour: datetime
    value: float | None
    expected: float | None = None


class GetSeriesOutput(ToolOutput):
    points: list[SeriesPoint]


class CheckFreshnessInput(_Strict):
    tables: list[str]
    window: Window


class CheckFreshnessOutput(ToolOutput):
    ok: bool
    tables: list[TableFreshness]


class CheckIdentitiesInput(_Strict):
    window: Window
    segment: Segment = Field(default_factory=dict)


class IdentityCheck(_Strict):
    edge: str
    expr: str
    max_rel_residual: float
    holds: bool


class CheckIdentitiesOutput(ToolOutput):
    ok: bool
    identities: list[IdentityCheck]


class DecomposeFormulaInput(_Strict):
    node: str
    segment: Segment = Field(default_factory=dict)
    window: Window


class DecomposeFormulaOutput(ToolOutput):
    node: str
    factors: list[str]
    contributions: list[Contribution]
    residual: float = Field(description="change minus the sum of contributions (LMDI: ~0)")


class MixRateSplitInput(_Strict):
    node: str = Field(description="ratio node")
    dim: str
    segment: Segment = Field(default_factory=dict)
    window: Window


class MixRateSplitOutput(ToolOutput):
    change: float
    mix: float
    rate: float
    rates_flat: bool = Field(description="every segment's own rate |z| < 2")


class SegmentSearchInput(_Strict):
    node: str
    segment: Segment = Field(default_factory=dict, description="search inside this slice")
    window: Window
    dims: list[str] | None = Field(default=None, description="default: all dims of the node")


class SegmentCell(_Strict):
    segment: Segment
    ep: float = Field(description="explanatory power: share of the total deviation in this cell")
    volume_share: float
    rel_change: float


class SegmentSearchOutput(ToolOutput):
    segment: Segment
    explained_share: float
    path: list[SegmentCell] = Field(description="the cells chosen while descending, coarsest first")


class ListEventsInput(_Strict):
    start: datetime
    end: datetime
    logs: list[str] | None = None
    covering: Segment | None = Field(default=None, description="only events whose scope covers this segment")


class ListEventsOutput(ToolOutput):
    events: list[EvidenceRef]


class HoldoutCheckInput(_Strict):
    event: EvidenceRef
    node: str
    segment: Segment = Field(description="the anomalous segment")
    window: Window


class HoldoutCheckOutput(ToolOutput):
    holdout: dict[str, Any] = Field(description="event scope minus the anomalous segment, as a SQL filter")
    rel_change: float | None
    z: float | None
    result: str = Field(description="consistent | refuted | not_applicable")


class PlaceboTestInput(_Strict):
    node: str
    segment: Segment
    window: Window
    weeks: int = 8


class PlaceboTestOutput(ToolOutput):
    hits: int
    weeks: int


class LagTestInput(_Strict):
    x: str
    y: str
    lags: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])


class LagTestOutput(ToolOutput):
    best_lag: int | None
    q_value: float | None


class CounterfactualImpactInput(_Strict):
    node: str
    segment: Segment
    window: Window


class CounterfactualImpactOutput(ToolOutput):
    per_hour: float
    so_far: float
    gmv_eur_per_hour: float


class ToolSpec(_Strict):
    name: str
    description: str
    input_model: str
    output_model: str
    implemented: bool
    owner: str


TOOL_MODELS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "get_series": (GetSeriesInput, GetSeriesOutput),
    "check_freshness": (CheckFreshnessInput, CheckFreshnessOutput),
    "check_identities": (CheckIdentitiesInput, CheckIdentitiesOutput),
    "decompose_formula": (DecomposeFormulaInput, DecomposeFormulaOutput),
    "mix_rate_split": (MixRateSplitInput, MixRateSplitOutput),
    "segment_search": (SegmentSearchInput, SegmentSearchOutput),
    "list_events": (ListEventsInput, ListEventsOutput),
    "holdout_check": (HoldoutCheckInput, HoldoutCheckOutput),
    "placebo_test": (PlaceboTestInput, PlaceboTestOutput),
    "lag_test": (LagTestInput, LagTestOutput),
    "counterfactual_impact": (CounterfactualImpactInput, CounterfactualImpactOutput),
}

TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_series",
        description="Hourly values and expectation of a node in a segment.",
        input_model="GetSeriesInput",
        output_model="GetSeriesOutput",
        implemented=False,
        owner="B",
    ),
    ToolSpec(
        name="check_freshness",
        description="Completeness of source tables for a window (data before business).",
        input_model="CheckFreshnessInput",
        output_model="CheckFreshnessOutput",
        implemented=True,
        owner="B",
    ),
    ToolSpec(
        name="check_identities",
        description="Do the cross-table formula identities hold in the window?",
        input_model="CheckIdentitiesInput",
        output_model="CheckIdentitiesOutput",
        implemented=True,
        owner="G",
    ),
    ToolSpec(
        name="decompose_formula",
        description="Exact LMDI split of a node's change along its formula edges.",
        input_model="DecomposeFormulaInput",
        output_model="DecomposeFormulaOutput",
        implemented=True,
        owner="B",
    ),
    ToolSpec(
        name="mix_rate_split",
        description="Split a ratio's change into segment mix and segment rate effects.",
        input_model="MixRateSplitInput",
        output_model="MixRateSplitOutput",
        implemented=False,
        owner="B",
    ),
    ToolSpec(
        name="segment_search",
        description="Smallest segment that explains >= 67% of the deviation, with descent.",
        input_model="SegmentSearchInput",
        output_model="SegmentSearchOutput",
        implemented=True,
        owner="B",
    ),
    ToolSpec(
        name="list_events",
        description="Log entries in a time range whose scope covers a segment.",
        input_model="ListEventsInput",
        output_model="ListEventsOutput",
        implemented=True,
        owner="B",
    ),
    ToolSpec(
        name="holdout_check",
        description="Is the event's scope outside the anomalous segment normal?",
        input_model="HoldoutCheckInput",
        output_model="HoldoutCheckOutput",
        implemented=True,
        owner="B",
    ),
    ToolSpec(
        name="placebo_test",
        description="Would the same analysis fire on the same hours of earlier weeks?",
        input_model="PlaceboTestInput",
        output_model="PlaceboTestOutput",
        implemented=False,
        owner="B",
    ),
    ToolSpec(
        name="lag_test",
        description="Lagged correlation of de-seasonalised residuals, BH corrected.",
        input_model="LagTestInput",
        output_model="LagTestOutput",
        implemented=False,
        owner="G",
    ),
    ToolSpec(
        name="counterfactual_impact",
        description="Orders and EUR lost against the expectation.",
        input_model="CounterfactualImpactInput",
        output_model="CounterfactualImpactOutput",
        implemented=True,
        owner="B",
    ),
)
