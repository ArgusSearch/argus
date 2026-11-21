"""JSON contract for a matched MockMart replay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.findings import EvidenceRef, Segment, Window

Scenario = Literal["s1", "s4"]
Metric = Literal["payment_success_rate", "pacing_ratio"]


class ReplayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorldConfig(ReplayModel):
    seed: int = Field(ge=0)
    days: int = Field(default=42, ge=32)
    live_days: int = Field(default=5, ge=4)


class ReplayPlan(ReplayModel):
    version: Literal["mockmart-paired-v1"] = "mockmart-paired-v1"
    scenario: Scenario
    config: WorldConfig
    intervention: EvidenceRef
    metric: Metric
    segment: Segment
    onset: datetime
    window: Window
    as_of: datetime


class QueryProof(ReplayModel):
    sql: str
    result_hash: str
    rows: int


class ReplayReceipt(ReplayModel):
    plan: ReplayPlan
    factual: QueryProof
    counterfactual: QueryProof


class Point(ReplayModel):
    hour: datetime
    value: float
    expected: float


class Gap(ReplayModel):
    factual: float
    counterfactual: float
    removed: float


class CounterfactualResult(ReplayModel):
    factual_series: list[Point]
    counterfactual_series: list[Point]
    explained_share: float = Field(ge=0, le=1)
    gap: Gap
    receipt: ReplayReceipt
