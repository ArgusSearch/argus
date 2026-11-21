"""Signature tests for S2, S3 and S4: each scenario leaves exactly the data pattern its truth claims, on 3 seeds."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from mockmart.scenarios.s4_pacer import _front_loaded_share
from mockmart.truth import read_truth

pytestmark = pytest.mark.e2e
SEEDS = (1, 2, 3)
END_AS_OF = datetime(2026, 11, 24)  # after the default world end: every row is visible


def _truth(paths, kind: str) -> dict:
    events = [e for e in read_truth(paths.truth) if e["kind"] == kind]
    assert len(events) == 1
    return events[0]


@pytest.mark.parametrize("seed", SEEDS)
def test_s2_budget_rises_as_planned(world, view, seed):
    paths = world("s2", seed)
    event = _truth(paths, "innocent")
    exp = event["expected"]
    assert exp["verdict"] == "EXPECTED" and exp["page"] is False
    adv, t0 = event["segment"]["advertiser_id"], event["start_ts"]
    v = view(paths.world).at(END_AS_OF)

    budget = v.at(t0 - timedelta(hours=12)).one(
        f"SELECT ts, daily_budget FROM log_ad_budgets WHERE id = '{exp['evidence']}'"
    )
    assert budget == (t0, event["magnitude"]["budget_after_eur"]), "the change is visible half a day ahead"
    assert v.one(f"SELECT count(*) FROM log_calendar WHERE id IN {tuple(exp['evidence_any'])}")[0] == 1
    v.at(END_AS_OF)

    line = f"advertiser_id = '{adv}' AND country = 'FR'"
    after = f"ts >= TIMESTAMP '{t0}' AND ts < TIMESTAMP '{t0 + timedelta(hours=24)}'"
    before = f"ts >= TIMESTAMP '{t0 - timedelta(hours=48)}' AND ts < TIMESTAMP '{t0 - timedelta(hours=24)}'"
    spend_after = v.one(f"SELECT sum(ad_spend) FROM fact_ads_hourly WHERE {line} AND {after}")[0]
    spend_before = v.one(f"SELECT sum(ad_spend) FROM fact_ads_hourly WHERE {line} AND {before}")[0]
    plan_after = v.one(f"SELECT sum(planned_spend) FROM fact_ad_plan_hourly WHERE {line} AND {after}")[0]
    uplift = event["magnitude"]["uplift"]
    assert spend_after / spend_before == pytest.approx(1 + uplift, rel=0.08)
    assert spend_after / plan_after == pytest.approx(1.0, rel=0.06), "delivery follows the new plan"
    # The plan's hourly share is the same every day, so an untouched line plans the same spend a week apart.
    plans = v.all(
        f"SELECT ts, sum(planned_spend) FROM fact_ad_plan_hourly WHERE NOT ({line}) AND ts IN "
        f"(TIMESTAMP '{t0 + timedelta(hours=3)}', TIMESTAMP '{t0 + timedelta(hours=3, days=-7)}') GROUP BY ts"
    )
    assert len(plans) == 2 and plans[0][1] == pytest.approx(plans[1][1]), "every other budget line keeps its plan"


@pytest.mark.parametrize("seed", SEEDS)
def test_s3_orders_stall_breaks_identity_then_backfills(world, view, seed):
    paths = world("s3", seed)
    event = _truth(paths, "data")
    exp = event["expected"]
    assert exp["verdict"] == "DATA_ISSUE" and exp["page"] is False
    t0, t1 = event["start_ts"], event["end_ts"]
    n_hours = int(event["magnitude"]["stalled_hours"])
    assert 3 <= n_hours <= 5 and t1 == t0 + timedelta(hours=n_hours)
    backfill_at = datetime.fromisoformat(exp["backfill_at"])
    v = view(paths.world)

    def hour_state(hour: datetime, as_of: datetime) -> tuple[float, float, float]:
        v.at(as_of)
        comp = v.one(
            f"SELECT sum(share) FROM log_ingestion WHERE table_name = 'fact_orders_hourly' AND ts = TIMESTAMP '{hour}'"
        )[0]
        pay_comp = v.one(
            f"SELECT sum(share) FROM log_ingestion WHERE table_name = 'fact_payments_hourly' "
            f"AND ts = TIMESTAMP '{hour}'"
        )[0]
        orders = v.one(f"SELECT sum(orders) FROM fact_orders_hourly WHERE ts = TIMESTAMP '{hour}'")[0]
        pays = v.one(f"SELECT sum(payment_successes) FROM fact_payments_hourly WHERE ts = TIMESTAMP '{hour}'")[0]
        return comp, pay_comp, orders / pays

    for k in range(n_hours):
        hour = t0 + timedelta(hours=k)
        comp, pay_comp, ratio = hour_state(hour, hour + timedelta(hours=2))
        assert comp == pytest.approx(0.55) and pay_comp == pytest.approx(1.0)
        assert 0.5 < ratio < 0.6, "orders = payment_successes is broken while the table is partial"
        comp, _, ratio = hour_state(hour, backfill_at + timedelta(hours=1))
        assert comp == pytest.approx(1.0) and ratio == 1.0, "the backfill restores the identity exactly"
    comp, _, ratio = hour_state(t1, t1 + timedelta(hours=2))
    assert comp == pytest.approx(1.0) and ratio == 1.0, "the first hour after the stall arrives on time"

    hotfix = v.at(END_AS_OF).one(f"SELECT ts, scope FROM log_deploys WHERE id = '{exp['ruled_out'][0]}'")
    assert t0 < hotfix[0] < t0 + timedelta(hours=1) and hotfix[1] == "{}"


@pytest.mark.parametrize("seed", SEEDS)
def test_s4_pacer_burns_de_fr_budgets_by_midday(world, view, seed):
    paths = world("s4", seed)
    event = _truth(paths, "fault")
    exp = event["expected"]
    day0 = event["start_ts"]
    assert exp["verdict"] == "SUPPORTED_CAUSE" and day0.hour == 0
    v = view(paths.world).at(END_AS_OF)
    deploy_ts = v.one(f"SELECT ts FROM log_deploys WHERE id = '{exp['evidence']}'")[0]
    assert day0 - timedelta(hours=1) < deploy_ts < day0
    pacer_lines = v.all("SELECT advertiser_id, country FROM log_ad_budgets WHERE kind = 'pacer_change'")
    assert sorted(c for _, c in pacer_lines) == ["DE"] * 5 + ["FR"] * 4, "every DE and FR budget line moves to 1.7"

    day = f"ts >= TIMESTAMP '{day0}' AND ts < TIMESTAMP '{day0 + timedelta(days=1)}'"
    rows = v.all(
        f"SELECT a.country, hour(a.ts) AS h, sum(a.ad_spend) AS spend, "
        f"(SELECT sum(p.planned_spend) FROM fact_ad_plan_hourly p WHERE p.ts = a.ts AND p.country = a.country) AS plan "
        f"FROM fact_ads_hourly a WHERE {day.replace('ts', 'a.ts')} GROUP BY a.country, a.ts"
    )
    by_country: dict[str, dict[int, tuple[float, float]]] = {}
    for country, h, spend, plan in rows:
        by_country.setdefault(country, {})[h] = (spend, plan)
    for country, hours in by_country.items():
        spend = sum(s for s, _ in hours.values())
        plan = sum(p for _, p in hours.values())
        assert spend / plan == pytest.approx(1.0, rel=0.08), f"{country}: the daily total looks normal"
        afternoon = sum(hours[h][0] for h in range(13, 24))
        morning_ratio = sum(hours[h][0] for h in range(0, 8)) / sum(hours[h][1] for h in range(0, 8))
        if country in ("DE", "FR"):
            assert afternoon == 0.0, f"{country}: budget burnt before 13:00"
            assert morning_ratio > 1.5
        else:
            assert afternoon > 0.4 * plan and 0.8 < morning_ratio < 1.25, f"{country}: holdout on pacer 1.6"


@pytest.mark.parametrize("seed", SEEDS)
def test_s4_leaves_traffic_untouched(world, view, seed):
    """Same seed, quiet vs S4: the shop funnel is identical, so 'traffic increased' is refutable."""
    q = view(world("quiet", seed).world).at(END_AS_OF)
    s = view(world("s4", seed).world).at(END_AS_OF)
    sql = "SELECT sum(sessions), sum(hash(ts, country, platform, channel, category, sessions)) FROM fact_funnel_hourly"
    assert q.one(sql) == s.one(sql)


def test_front_loaded_share_burns_at_the_given_time():
    plan = np.full(24, 1 / 24)
    share = _front_loaded_share(plan, 10.5)
    assert share.sum() == pytest.approx(1.0)
    assert share[11:].sum() == 0.0 and share[10] == pytest.approx(share[9] / 2)
