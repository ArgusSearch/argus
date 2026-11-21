"""S2: a big advertiser in France raises its daily budget by about 40%, as planned and announced.

This is the innocent change. Spend, impressions and clicks of that budget line jump, and so does the
pacing plan, so delivered spend / planned spend stays normal. Argus must conclude EXPECTED and not page
anyone ("didn't wake you"), citing the budget change in `log_ad_budgets`.

Randomised per seed: the advertiser (one of the large FR lines), the uplift (+30..+50%), and the
effective hour (on live day 2 or 3, between 06:00 and 14:00). The change is logged a day or more ahead,
like a real planned change, and it stays in force until the end of the world.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from mockmart.sim import TruthEvent, WorldParams

ROOT_NODE = "ad_spend"
COUNTRY = "FR"
MIN_BUDGET_EUR = 1500.0  # "a big advertiser": only FR lines at or above this daily budget qualify
QUIET_LIVE_DAYS = 2
# Nodes that legitimately move with the budget: a page on any of them in this segment is a false alarm.
AFFECTED_NODES = ["ad_spend", "ad_impressions", "ad_clicks", "ad_conversions", "attributed_gmv", "planned_spend"]


def apply_s2(params: WorldParams, rng: np.random.Generator) -> None:
    cfg = params.cfg
    lines = params.ad_lines
    big = lines.index[(lines.country == COUNTRY) & (lines.base_budget >= MIN_BUDGET_EUR)].to_numpy()
    line_idx = int(rng.choice(big))
    line = lines.loc[line_idx]
    advertiser = str(line.advertiser_id)
    uplift = round(float(rng.uniform(0.30, 0.50)), 2)
    before = float(line.base_budget)
    after = round(before * (1.0 + uplift), 0)

    day = cfg.live_start + timedelta(days=QUIET_LIVE_DAYS + int(rng.integers(0, 2)))
    t0 = day + timedelta(hours=int(rng.integers(6, 15)))
    onset_h = params.hour_index(t0)
    params.ad_budget[onset_h:, line_idx] = after
    announced = t0 - timedelta(days=1, hours=int(rng.integers(0, 24)))

    segment = {"advertiser_id": advertiser, "country": COUNTRY}
    scope = {"advertiser_id": [advertiser], "country": [COUNTRY]}
    budget_id = f"bud_{advertiser}_{COUNTRY}_increase"
    calendar_id = f"cal_{advertiser}_{COUNTRY}_push"
    params.add_log(
        "log_ad_budgets",
        {
            "id": budget_id,
            "ts": t0,
            "ingested_at": announced,
            "kind": "budget_change",
            "scope": scope,
            "description": (
                f"{line['name']} {COUNTRY}: planned daily budget increase EUR {before:.0f} -> {after:.0f} "
                f"(+{uplift:.0%}) from {t0:%a %H:%M}, pacer 1.6"
            ),
            "advertiser_id": advertiser,
            "country": COUNTRY,
            "daily_budget": after,
            "pacer_version": "1.6",
        },
    )
    params.add_log(
        "log_calendar",
        {
            "id": calendar_id,
            "ts": t0,
            "ingested_at": announced,
            "end_ts": cfg.end,
            "kind": "campaign",
            "scope": scope,
            "description": f"{line['name']} seasonal push in {COUNTRY}: budget +{uplift:.0%}",
            "planned_uplift": {"ad_spend": uplift, "planned_spend": uplift},
        },
    )
    params.truth.append(
        TruthEvent(
            event_id="s2_planned_budget_increase",
            scenario="s2",
            kind="innocent",
            start_ts=t0,
            end_ts=None,
            root_node=ROOT_NODE,
            segment=dict(segment),
            magnitude={"budget_before_eur": before, "budget_after_eur": after, "uplift": uplift},
            description=f"planned +{uplift:.0%} budget increase for {advertiser} in {COUNTRY}; delivery follows plan",
            expected={
                "verdict": "EXPECTED",
                "root_node": ROOT_NODE,
                "segment": dict(segment),
                "evidence": budget_id,
                "evidence_any": [budget_id, calendar_id],
                "page": False,
                "affected_nodes": list(AFFECTED_NODES),
            },
        )
    )
