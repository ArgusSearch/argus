"""C4 findings: receipts, anomalies, investigation findings, notes and incidents.

Rule: every number shown to a human comes from a query, and that query is a `Receipt`.
A receipt pins `as_of`, so re-running its SQL returns the same `result_hash`.
`Quantity` carries a number together with the receipt it came from.

Verdicts:

* SUPPORTED_CAUSE: passes the first-cause test and the holdout check, and explains >= 20% of the change.
* HYPOTHESIS: consistent but not confirmed; the findings say which evidence would upgrade it.
* EXPECTED: a planned event inside its expected band, or an innocent mix shift ("didn't wake you").
* DATA_ISSUE: freshness or identity failure; re-checked after the backfill.
* UNEXPLAINED: the remainder after stopping, always stated as a number.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Segment = dict[str, str]
"""A segment maps dimension names to one value each, e.g. {"country": "DE", "platform": "android"}.
The empty dict is the whole business."""

Direction = Literal["up", "down"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Receipt(_Strict):
    id: str = Field(description="r1, r2, ... unique within a run")
    sql: str = Field(description="self-contained SQL (literals inlined), runs against the fact_/log_ views")
    as_of: datetime = Field(description="value of getvariable('as_of') when the query ran")
    result_hash: str = Field(description="sha256 over canonical rows: sorted, floats at 10 significant digits")
    rows: int
    ms: float
    purpose: str = Field(default="", description="why the query ran, shown in the receipt drawer")


class Quantity(_Strict):
    value: float
    unit: str = Field(description="count | eur | share | pct | ratio | z | hours")
    receipt: str | None = Field(description="receipt id; None only for values derived from other quantities")


class TableFreshness(_Strict):
    table: str
    hour: datetime
    completeness: float = Field(description="0..1, SUM(share) of delivered batches")
    status: Literal["ok", "pending"]


class Anomaly(_Strict):
    id: str = Field(description="an_0001, ...")
    node: str
    segment: Segment = Field(default_factory=dict)
    direction: Direction
    hour: datetime = Field(description="the scored data hour")
    detected_at: datetime = Field(description="as_of of the tick that opened the anomaly")
    onset: datetime = Field(description="first hour of the run with |z| > 2")
    observed: float
    expected: float
    band: tuple[float, float] = Field(description="expected +- 2 sigma")
    z: float
    rule: Literal["z_gt_4", "two_of_three_gt_3", "pacing"]
    data_confidence: float = 1.0
    receipts: list[str] = Field(default_factory=list)


class Verdict(StrEnum):
    SUPPORTED_CAUSE = "SUPPORTED_CAUSE"
    HYPOTHESIS = "HYPOTHESIS"
    EXPECTED = "EXPECTED"
    DATA_ISSUE = "DATA_ISSUE"
    UNEXPLAINED = "UNEXPLAINED"


class TrailStep(_Strict):
    """One step of an investigation. The SQL behind it is in `receipts`."""

    step: int
    kind: Literal[
        "freshness", "identities", "calendar", "decompose", "segment", "events", "holdout", "impact", "verdict"
    ]
    tool: str = Field(description="C6 tool name that produced the result")
    hypothesis: str | None = None
    prediction: str | None = Field(default=None, description="written before the query runs")
    result: str
    decision: str
    why: str = ""
    receipts: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict, description="structured result for the UI")


class EvidenceRef(_Strict):
    log: str = Field(description="log view, e.g. log_provider_status")
    ref: str = Field(description="id of the log row")
    ts: datetime
    kind: str
    description: str
    scope: dict[str, list[str]] = Field(default_factory=dict)


class RootCause(_Strict):
    node: str
    segment: Segment
    direction: Direction
    evidence: EvidenceRef | None = None
    change_pct: Quantity


class ObservedChange(_Strict):
    node: str
    segment: Segment
    observed: Quantity
    expected: Quantity
    change_pct: Quantity


class Contribution(_Strict):
    """One factor of an exact LMDI split (shares sum to 1 over factors plus 'unexplained')."""

    node: str
    share: float
    value: float = Field(description="absolute contribution to the change of the decomposed node")
    receipt: str | None


class Impact(_Strict):
    node: str = Field(description="north-star node the impact is measured on")
    segment: Segment
    hours: int
    per_hour: Quantity
    gmv_eur_per_hour: Quantity
    eur_so_far: Quantity


class RuledOut(_Strict):
    hypothesis: str
    prediction: str
    result: Literal["refuted", "inconclusive"]
    reason: str
    evidence: EvidenceRef | None = None
    receipts: list[str] = Field(default_factory=list)


class SuggestedAction(_Strict):
    text: str
    needs_approval: bool = True


class Cost(_Strict):
    queries: int
    seconds: float
    llm_calls: int = 0
    eur: float = 0.0


class SkepticResult(_Strict):
    """Reserved for lane B (skeptic). Absent until the skeptic runs."""

    verdict: Literal["upheld", "weakened", "refuted"]
    checks: list[dict[str, Any]] = Field(default_factory=list)


class Window(_Strict):
    start: datetime = Field(description="first data hour (inclusive)")
    end: datetime = Field(description="last data hour (inclusive)")


class Findings(_Strict):
    """Structured result of one investigation. The narrator writes prose only from this object."""

    anomaly_id: str
    incident_id: str | None = None
    verdict: Verdict
    headline: str
    as_of: datetime
    window: Window
    observed: ObservedChange
    root: RootCause | None = None
    decomposition: list[Contribution] = Field(default_factory=list)
    decomposed_node: str | None = None
    impact: Impact | None = None
    ruled_out: list[RuledOut] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    explained_share: float = Field(ge=0.0, le=1.0)
    unexplained_share: float = Field(ge=0.0, le=1.0)
    trail: list[TrailStep] = Field(default_factory=list)
    skeptic: SkepticResult | None = None
    cost: Cost
    suggested_action: SuggestedAction | None = None


class Note(_Strict):
    """Something Argus noticed but did not page for ("didn't wake you"), or a data issue."""

    id: str
    kind: Literal["expected", "data_issue", "suppressed"]
    sim_ts: datetime
    node: str | None = None
    segment: Segment = Field(default_factory=dict)
    reason: str
    numbers: list[Quantity] = Field(default_factory=list)
    receipts: list[str] = Field(default_factory=list)


class IncidentState(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    EXPLAINED = "explained"
    MONITORING = "monitoring"
    RESOLVED = "resolved"


class IncidentTransition(_Strict):
    sim_ts: datetime
    from_state: IncidentState | None
    to_state: IncidentState
    reason: str


class Incident(_Strict):
    """One problem, one incident. Fingerprint = (root node, segment, direction)."""

    id: str = Field(description="INC-0001, ...")
    fingerprint: str
    title: str
    verdict: Verdict
    state: IncidentState
    root_node: str
    segment: Segment
    direction: Direction
    severity_eur: float = Field(description="cumulative EUR impact against the expectation, not z")
    opened_at: datetime = Field(description="data hour of the anomaly that opened it")
    updated_at: datetime
    resolved_at: datetime | None = None
    reopened: int = 0
    anomalies: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list, description="nodes whose alerts this incident silences")
    history: list[IncidentTransition] = Field(default_factory=list)
    findings: Findings
