"""Pure parts of the Stage-2 layer: factor choice, hop paths, week statistics, control filters."""

from __future__ import annotations

from datetime import datetime

import pytest

from argus.contracts.findings import Window
from argus.graph.store import load_seed_graph
from argus.investigate.tools import neighbours_where
from argus.investigate.walk import FactorView, choose_factor, hops, leaves, subtree_share
from argus.investigate.weekly import WeeklySeries, WeekValue, week_stat, weekly_sql

GRAPH = load_seed_graph()


def test_walk_follows_the_significant_factor_not_the_noisy_one() -> None:
    # orders -3%: traffic noise carries more of the change than the payment fault, but only the fault is unusual
    factors = [
        FactorView("sessions", contribution=-120.0, share=0.6, z=-1.1),
        FactorView("payment_success_rate", contribution=-90.0, share=0.45, z=-9.5),
        FactorView("cart_rate", contribution=10.0, share=-0.05, z=0.4),
    ]
    chosen, significant = choose_factor(factors, change=-200.0)
    assert chosen.node == "payment_success_rate" and significant


def test_walk_falls_back_to_the_largest_share_and_says_it_is_weak() -> None:
    factors = [FactorView("sessions", -50.0, 0.7, z=-1.0), FactorView("cart_rate", -20.0, 0.3, z=-0.5)]
    chosen, significant = choose_factor(factors, change=-70.0)
    assert chosen.node == "sessions" and not significant
    with pytest.raises(ValueError):
        choose_factor([], change=1.0)


def test_hops_rebuild_the_path_through_the_graph() -> None:
    path = hops(GRAPH, "gmv", "payment_success_rate")
    assert [(h.node, h.follow) for h in path] == [("gmv", "orders"), ("orders", "cvr"), ("cvr", "payment_success_rate")]
    assert hops(GRAPH, "payment_success_rate", "payment_success_rate") == []
    assert "payment_success_rate" in leaves(GRAPH, "orders")
    shares = {
        "sessions": 0.1,
        "view_rate": 0.0,
        "cart_rate": 0.0,
        "checkout_rate": 0.0,
        "attempt_rate": -0.05,
        "payment_success_rate": 0.95,
    }
    assert subtree_share(GRAPH, "cvr", shares) == pytest.approx(0.9)


def test_week_stat_uses_the_week_spread_as_the_scale() -> None:
    noisy = WeeklySeries(
        node="sessions",
        is_ratio=False,
        is_share=False,
        weeks={
            0: WeekValue(0, 103_000),
            **{k: WeekValue(k, v) for k, v in enumerate([100_000, 97_000, 104_000, 99_000], 1)},
        },
        receipts=("r1",),
    )
    stat = week_stat(noisy)
    assert stat is not None and stat.baseline == 100_000 and abs(stat.z) < 1.5
    share = WeeklySeries(
        node="payment_success_rate",
        is_ratio=True,
        is_share=True,
        weeks={0: WeekValue(0, 880, 1000), **{k: WeekValue(k, 950, 1000) for k in range(1, 5)}},
        receipts=("r1",),
    )
    stat = week_stat(share)
    assert stat is not None and stat.baseline == pytest.approx(0.95) and stat.z < -9
    assert week_stat(share, 0, [1]) is None  # one baseline week is not a spread


def test_weekly_sql_and_neighbour_filters() -> None:
    window = Window(start=datetime(2026, 11, 20, 21), end=datetime(2026, 11, 20, 23))
    sql = weekly_sql("fact_payments_hourly", ["payment_attempts"], window, "country = 'DE'", weeks=2)
    assert "WHEN ts BETWEEN TIMESTAMP '2026-11-06 21:00:00' AND TIMESTAMP '2026-11-06 23:00:00' THEN 2" in sql
    assert "COUNT(DISTINCT ts) AS hours" in sql and "GROUP BY week" in sql
    assert neighbours_where({}) is None
    assert neighbours_where({"provider": "PayCo"}) == "provider <> 'PayCo'"
    where = neighbours_where({"country": "DE", "platform": "android"})
    assert where == "(platform = 'android' AND country <> 'DE') OR (country = 'DE' AND platform <> 'android')"
