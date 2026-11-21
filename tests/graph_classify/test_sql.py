"""Lineage, guards and units: the deterministic part of self-classification, no data needed."""

from __future__ import annotations

import numpy as np
import pytest

from argus.contracts.graph import NodeKind
from argus.contracts.metric import MetricSqlError
from argus.graph.classify_sql import (
    fanout_problems,
    hourly_as_written,
    label_of,
    lineage,
    name_hint,
    repair_sql,
    segment_of,
    unit_of,
)
from argus.graph.store import load_seed_graph

GRAPH = load_seed_graph()
ORDERS_X_FUNNEL = "FROM fact_orders_hourly JOIN fact_funnel_hourly USING (ts, country, platform, channel, category)"
PAYMENTS_X_FUNNEL = "FROM fact_payments_hourly JOIN fact_funnel_hourly USING (ts, country, platform)"


def test_cross_table_ratio_maps_to_existing_nodes() -> None:
    sql = f"SELECT ts, country, SUM(gmv) / NULLIF(SUM(sessions), 0) AS value {ORDERS_X_FUNNEL} GROUP BY ALL"
    lin = lineage(sql, GRAPH, "revenue_per_session")
    assert (lin.kind, lin.numerator, lin.denominator, lin.expr) == (NodeKind.RATIO, "gmv", "sessions", "gmv / sessions")
    assert lin.ingredients == ["gmv", "sessions"]


def test_casts_and_aliases_are_seen_through() -> None:
    value = "SUM(a.ad_conversions)::DOUBLE / NULLIF(SUM(a.ad_clicks), 0)"
    sql = f"SELECT ts, {value} AS value FROM fact_ads_hourly a GROUP BY ALL"
    lin = lineage(sql, GRAPH, "x")
    assert (lin.numerator, lin.denominator) == ("ad_conversions", "ad_clicks")


def test_plain_sum_is_the_existing_additive_node() -> None:
    lin = lineage("SELECT ts, SUM(sessions) AS value FROM fact_funnel_hourly GROUP BY ALL", GRAPH, "x")
    assert (lin.kind, lin.expr, lin.missing) == (NodeKind.ADDITIVE, "sessions", None)


def test_constants_and_differences_are_derived() -> None:
    sql = "SELECT ts, SUM(payment_attempts) - SUM(payment_successes) AS value FROM fact_payments_hourly GROUP BY ALL"
    assert lineage(sql, GRAPH, "x").expr == "payment_attempts - payment_successes"
    sql = f"SELECT ts, 100.0 * SUM(orders) / NULLIF(SUM(sessions), 0) AS value {ORDERS_X_FUNNEL} GROUP BY ALL"
    lin = lineage(sql, GRAPH, "x")
    assert (lin.kind, lin.expr) == (NodeKind.DERIVED, "100.0 * orders / sessions")


def test_a_measure_without_a_node_becomes_the_node() -> None:
    graph = GRAPH.model_copy(update={"nodes": [n for n in GRAPH.nodes if n.id != "planned_spend"], "edges": []})
    graph = graph.model_copy(update={"nodes": [n for n in graph.nodes if n.id != "pacing_ratio"]})
    lin = lineage("SELECT ts, SUM(planned_spend) AS value FROM fact_ad_plan_hourly GROUP BY ALL", graph, "plan")
    assert lin.missing == ("fact_ad_plan_hourly", "planned_spend")
    with pytest.raises(MetricSqlError, match="has no node yet"):
        lineage(
            "SELECT ts, SUM(planned_spend) / SUM(planned_spend) AS value FROM fact_ad_plan_hourly GROUP BY ALL",
            graph,
            "x",
        )


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("COUNT(*)", "COUNT counts rows"),
        ("SUM(payment_attempts - payment_successes)", "SUM must wrap one measure column"),
        ("SUM(country)", "is not a measure"),
    ],
)
def test_unplaceable_values_are_rejected_with_a_reason(value: str, reason: str) -> None:
    with pytest.raises(MetricSqlError, match=reason):
        lineage(f"SELECT ts, {value} AS value FROM fact_payments_hourly GROUP BY ALL", GRAPH, "x")


def test_where_is_a_segment() -> None:
    base = "SELECT ts, SUM(sessions) AS value FROM fact_funnel_hourly WHERE {} GROUP BY ALL"
    assert segment_of(base.format("channel = 'paid' AND (country = 'DE')")) == {"channel": "paid", "country": "DE"}
    assert segment_of("SELECT ts, SUM(sessions) AS value FROM fact_funnel_hourly GROUP BY ALL") == {}
    for bad, reason in [
        ("channel = 'paid' OR country = 'DE'", "only dim = 'value'"),
        ("country = 'XX'", "not a known value"),
        ("country = 'DE' AND country = 'FR'", "two values"),
        ("sessions > 10", "only dim = 'value'"),
    ]:
        with pytest.raises(MetricSqlError, match=reason):
            segment_of(base.format(bad))


def test_fanout_guard_flags_joins_below_the_grain() -> None:
    bad = f"SELECT ts, SUM(payment_successes) / SUM(sessions) AS value {PAYMENTS_X_FUNNEL} GROUP BY ALL"
    problems = fanout_problems(bad)
    assert len(problems) == 2
    assert "provider" in problems[0] and "up to 3" in problems[0]
    assert "channel, category" in problems[1] and "up to 24" in problems[1]
    good = f"SELECT ts, SUM(gmv) / SUM(sessions) AS value {ORDERS_X_FUNNEL} GROUP BY ALL"
    assert fanout_problems(good) == []


def test_hourly_as_written_keeps_the_filter_and_groups_by_hour() -> None:
    sql = "SELECT ts, country, SUM(sessions) AS value FROM fact_funnel_hourly WHERE channel = 'paid' GROUP BY ALL"
    out = hourly_as_written(sql, "ts >= TIMESTAMP '2026-10-01 00:00:00'")
    assert "country" not in out.split("FROM")[0]
    assert "channel = 'paid'" in out and "GROUP BY ts" in out and "ORDER BY ts" in out


def test_repair_aggregates_each_view_before_dividing() -> None:
    sql = f"SELECT ts, country, SUM(payment_successes) / SUM(sessions) AS value {PAYMENTS_X_FUNNEL} GROUP BY ALL"
    lin = lineage(sql, GRAPH, "x")
    fixed = repair_sql(sql, GRAPH, lin, ["country"])
    assert "FROM fact_payments_hourly GROUP BY ALL" in fixed and "FROM fact_funnel_hourly GROUP BY ALL" in fixed
    assert "JOIN den USING (ts, country)\n" in fixed + "\n"


def test_units_by_dimensional_analysis() -> None:
    units = {n.id: n.unit for n in GRAPH.nodes}
    assert unit_of("gmv / sessions", units)[0] == "eur_per_unit"
    assert unit_of("attributed_gmv / ad_spend", units, np.array([2.0, 3.0]))[0] == "ratio"
    assert unit_of("orders / checkouts", units, np.array([0.4, 0.5]))[0] == "share"
    assert unit_of("sessions / orders", units, np.array([20.0, 30.0]))[0] == "ratio"
    assert unit_of("gmv - orders", units)[1].startswith("adds quantities of different units")


def test_labels_and_name_hints() -> None:
    assert label_of("roas_by_advertiser") == "ROAS by advertiser"
    assert label_of("revenue_per_session") == "Revenue per session"
    assert name_hint("roas_by_advertiser", GRAPH) == "roas"
    assert name_hint("revenue_per_session", GRAPH) is None
