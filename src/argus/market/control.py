"""Compare a traffic-sensitive metric with a market demand control at the same data hour."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from argus.contracts.findings import Anomaly, Segment, Window
from argus.contracts.graph import Graph, NodeKind
from argus.semantic.compile import BASELINE_WEEKS, baseline_condition, hourly_sql, quote, window_condition
from argus.semantic.runner import Runner, sql_ts
from argus.watcher.freshness import COMPLETE

CONTROL_SOURCE = "market_demand_hourly"
CONTROLLED_NODES = frozenset({"sessions", "orders", "gmv"})
EVIDENCE_HOURS = 12
MIN_BASELINE_WEEKS = 3
MIN_DROP_PCT = 12.0
RESIDUAL_BAND_PCT = 8.0
MarketVerdict = Literal["market", "us", "inconclusive"]


class MarketPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ts: datetime
    metric_value: float
    metric_expected: float
    control_value: float
    control_expected: float
    metric_change_pct: float
    control_change_pct: float
    adjusted_expected: float
    residual_pct: float
    baseline_weeks: int


class MarketAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: MarketVerdict
    node: str
    segment: Segment
    control: str
    hour: datetime
    reason: str
    receipt_id: str
    series: list[MarketPoint]


def check_control_group(runner: Runner, graph: Graph, anomaly: Anomaly, as_of: datetime) -> MarketAssessment | None:
    """Return evidence if an eligible drop has a complete metric/control pair and enough matched history."""
    if anomaly.direction != "down" or anomaly.rule == "pacing" or anomaly.node not in CONTROLLED_NODES:
        return None
    node = graph.node(anomaly.node)
    if node.kind is not NodeKind.ADDITIVE or not node.table:
        return None

    available = runner.fetch(
        f"SELECT 1 FROM information_schema.views WHERE table_schema = 'main' AND table_name = {quote(CONTROL_SOURCE)}",
        as_of,
    )
    if not available:
        return None

    window = Window(start=anomaly.hour - timedelta(hours=EVIDENCE_HOURS - 1), end=anomaly.hour)
    condition = f"({window_condition(window)} OR {baseline_condition(window)})"
    metric = hourly_sql(graph, node.id, condition, anomaly.segment)
    rows, receipt = runner.query(
        f"""
        WITH metric AS ({metric}),
        complete_hours AS (
            SELECT ts
            FROM log_ingestion
            WHERE table_name = {quote(node.table)} AND {condition}
            GROUP BY ts HAVING SUM(share) >= {COMPLETE}
        ),
        pairs AS (
            SELECT m.ts, m.value::DOUBLE AS metric_value, c.demand_index AS control_value
            FROM metric m
            JOIN complete_hours USING (ts)
            JOIN {CONTROL_SOURCE} c USING (ts)
            WHERE m.value >= 0 AND isfinite(m.value::DOUBLE)
              AND c.demand_index > 0 AND isfinite(c.demand_index)
        ),
        baselines AS (
            SELECT current_pair.ts, MEDIAN(prior.metric_value) AS metric_expected,
                   MEDIAN(prior.control_value) AS control_expected, COUNT(*) AS baseline_weeks
            FROM pairs current_pair
            CROSS JOIN range(1, {BASELINE_WEEKS + 1}) AS offsets(week_num)
            JOIN pairs prior ON prior.ts = current_pair.ts - offsets.week_num * INTERVAL '1 week'
            WHERE current_pair.ts BETWEEN {sql_ts(window.start)} AND {sql_ts(window.end)}
            GROUP BY current_pair.ts
            HAVING COUNT(*) >= {MIN_BASELINE_WEEKS} AND MEDIAN(prior.metric_value) > 0
        ),
        adjusted AS (
            SELECT p.*, b.metric_expected, b.control_expected, b.baseline_weeks,
                   b.metric_expected * p.control_value / b.control_expected AS adjusted_expected
            FROM pairs p JOIN baselines b USING (ts)
        )
        SELECT *,
               100 * (metric_value / metric_expected - 1) AS metric_change_pct,
               100 * (control_value / control_expected - 1) AS control_change_pct,
               100 * (metric_value / adjusted_expected - 1) AS residual_pct
        FROM adjusted ORDER BY ts
        """,
        as_of,
        f"Compare {node.id} against independent market demand and matched weekly baselines",
    )
    if not rows or rows[-1]["ts"] != anomaly.hour:
        return None
    series = [MarketPoint.model_validate(row) for row in rows]
    current = series[-1]
    verdict: MarketVerdict = "inconclusive"
    reason = "The comparison does not establish a shared decline or a material local shortfall."
    if current.metric_change_pct <= -MIN_DROP_PCT:
        if current.residual_pct < -RESIDUAL_BAND_PCT:
            verdict = "us"
            reason = (
                "The metric fell below its market-adjusted expectation. Continue investigating the local shortfall."
            )
        elif current.control_change_pct <= -MIN_DROP_PCT and abs(current.residual_pct) <= RESIDUAL_BAND_PCT:
            verdict = "market"
            reason = "The metric tracked the market-wide decline within the residual band."
    return MarketAssessment(
        verdict=verdict,
        node=node.id,
        segment=anomaly.segment,
        control=CONTROL_SOURCE,
        hour=anomaly.hour,
        reason=reason,
        receipt_id=receipt.id,
        series=series,
    )
