"""Planned changes: the watcher looks at the segment a budget change or calendar entry names.

The worlds mirror S2 (a planned budget increase for one advertiser in FR, announced a day ahead in
`log_ad_budgets` and `log_calendar`), built here with the simulator's hooks so the test runs on any branch.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import numpy as np
import pytest

from argus.contracts.graph import Graph
from argus.detect import Watcher, WatcherConfig
from argus.detect.planned import PlannedChanges, relation, step_z
from argus.semantic.runner import Runner
from mockmart.sim import WorldParams

from .conftest import World

ADVERTISER, COUNTRY = "adv_03", "FR"  # the smallest "big" FR line (EUR 1500 a day): the hardest to see
SEGMENT = {"advertiser_id": ADVERTISER, "country": COUNTRY}
EFFECT_AFTER_LIVE = timedelta(days=2, hours=9)


def planned_increase(uplift: float, delivered: bool = True) -> Callable[[WorldParams], None]:
    """Announce +uplift for the line a day ahead; `delivered=False` leaves the budget unchanged."""

    def mutate(params: WorldParams) -> None:
        lines = params.ad_lines
        idx = int(lines.index[(lines.advertiser_id == ADVERTISER) & (lines.country == COUNTRY)][0])
        before = float(lines.loc[idx, "base_budget"])
        after = round(before * (1.0 + uplift))
        t0 = params.cfg.live_start + EFFECT_AFTER_LIVE
        if delivered:
            params.ad_budget[params.hour_index(t0) :, idx] = after
        scope = {"advertiser_id": [ADVERTISER], "country": [COUNTRY]}
        announced = t0 - timedelta(days=1)
        params.add_log(
            "log_ad_budgets",
            {
                "id": f"bud_{ADVERTISER}_{COUNTRY}_increase",
                "ts": t0,
                "ingested_at": announced,
                "kind": "budget_change",
                "scope": scope,
                "description": f"planned daily budget increase EUR {before:.0f} -> {after:.0f}",
                "advertiser_id": ADVERTISER,
                "country": COUNTRY,
                "daily_budget": after,
                "pacer_version": "1.6",
            },
        )
        params.add_log(
            "log_calendar",
            {
                "id": f"cal_{ADVERTISER}_{COUNTRY}_push",
                "ts": t0,
                "ingested_at": announced,
                "end_ts": params.cfg.end,
                "kind": "campaign",
                "scope": scope,
                "description": f"seasonal push: budget +{uplift:.0%}",
                "planned_uplift": {"ad_spend": uplift, "planned_spend": uplift},
            },
        )

    return mutate


def test_step_z_pools_the_hours_since_the_change() -> None:
    z, n = step_z(np.array([3.0, 3.0, np.nan, 3.0]))
    assert n == 3 and z == pytest.approx(3.0 * np.sqrt(3))
    assert np.isnan(step_z(np.array([np.nan]))[0])


def test_relation_of_a_series_to_a_change_scope() -> None:
    assert relation(SEGMENT, {**SEGMENT, "platform": "ios"}) == "inside"
    assert relation(SEGMENT, SEGMENT) == "inside"
    assert relation(SEGMENT, {"advertiser_id": ADVERTISER}) == "contains"
    assert relation(SEGMENT, {}) == "contains"
    assert relation(SEGMENT, {"country": "DE"}) is None


@pytest.mark.e2e
def test_planned_changes_are_read_once_per_line_with_their_uplift(
    make_world: Callable[..., World], graph: Graph
) -> None:
    world = make_world("quiet", 7, mutate=planned_increase(0.4), tag="-plan40")
    found = PlannedChanges(Runner(world.path), graph).refresh(world.end)
    named = [c for c in found if not c.derived]
    assert [(c.node, c.is_plan) for c in named] == [("ad_spend", False), ("planned_spend", True)]
    # the budget line's other measures in fact_ads_hourly move with it
    assert {c.node for c in found if c.derived} == {"ad_impressions", "ad_clicks", "ad_conversions", "attributed_gmv"}
    spend = named[0]
    assert spend.segment == SEGMENT and spend.start == world.live_start + EFFECT_AFTER_LIVE
    assert spend.uplift == pytest.approx(0.4, abs=0.001)
    assert spend.ids == (f"bud_{ADVERTISER}_{COUNTRY}_increase", f"cal_{ADVERTISER}_{COUNTRY}_push")
    assert spend.end == world.cfg.end  # the calendar entry's end
    assert PlannedChanges(Runner(make_world("quiet", 7).path), graph).refresh(world.end) == []


@pytest.mark.e2e
@pytest.mark.parametrize("uplift", [0.3, 0.5])
def test_a_planned_increase_opens_one_anomaly_on_its_line(
    make_world: Callable[..., World], graph: Graph, uplift: float
) -> None:
    world = make_world("quiet", 7, mutate=planned_increase(uplift), tag=f"-plan{uplift}")
    t0 = world.live_start + EFFECT_AFTER_LIVE
    runner = Runner(world.path)
    watcher = Watcher(runner, graph)
    # through the night and the next day: once in force, the plan lifts the expectation of the line and of
    # every wider series that holds it, so nothing else pages on the same change
    for _ in watcher.run(t0 - timedelta(hours=6), t0 + timedelta(hours=36)):
        pass

    assert len(watcher.anomalies) == 1, [(a.node, a.segment, a.rule) for a in watcher.anomalies]
    anomaly = watcher.anomalies[0]
    assert (anomaly.node, anomaly.segment, anomaly.direction) == ("ad_spend", SEGMENT, "up")
    assert anomaly.rule == "z_gt_open" and anomaly.z > 5
    assert anomaly.onset == t0
    assert anomaly.detected_at - t0 <= timedelta(hours=8)
    assert anomaly.observed > anomaly.expected
    assert all(runner.rerun(rid)[1] for rid in anomaly.receipts)


@pytest.mark.e2e
def test_a_plan_that_is_not_delivered_is_an_alert(make_world: Callable[..., World], graph: Graph) -> None:
    world = make_world("quiet", 7, mutate=planned_increase(0.4, delivered=False), tag="-plan-missed")
    t0 = world.live_start + EFFECT_AFTER_LIVE
    watcher = Watcher(Runner(world.path), graph)
    for _ in watcher.run(t0 - timedelta(hours=2), t0 + timedelta(hours=14)):
        pass

    assert [(a.node, a.segment, a.direction) for a in watcher.anomalies] == [("ad_spend", SEGMENT, "down")]
    anomaly = watcher.anomalies[0]
    assert anomaly.onset == t0 and anomaly.z < -5
    assert anomaly.expected > anomaly.observed  # the expectation includes the plan


@pytest.mark.e2e
def test_check_plans_alone_routes_the_same_anomaly(make_world: Callable[..., World], graph: Graph) -> None:
    """The narrow entry point for a runtime that keeps its own detector for totals."""
    world = make_world("quiet", 7, mutate=planned_increase(0.5), tag="-plan0.5")
    t0 = world.live_start + EFFECT_AFTER_LIVE
    watcher = Watcher(Runner(world.path), graph, WatcherConfig(anomaly_prefix="an_plan_"))
    opened = []
    as_of = t0 - timedelta(hours=2)
    while as_of <= t0 + timedelta(hours=14):
        opened += watcher.check_plans(as_of)
        as_of += timedelta(hours=1)
    assert [(a.id, a.node, a.segment, a.direction) for a in opened] == [("an_plan_0001", "ad_spend", SEGMENT, "up")]
    assert opened[0].onset == t0
