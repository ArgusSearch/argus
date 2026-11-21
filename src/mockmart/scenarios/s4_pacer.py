"""S4: ad-pacer 1.7 rolls out for the DE and FR budget lines and stops following the hourly plan.

The broken pacer spends as fast as traffic allows, so every DE/FR budget is used up by about 10:00 and
nothing is delivered in the afternoon and evening. The daily total spend looks normal; the intraday
shape does not. Sessions are untouched ("traffic increased" is wrong), and the budget lines that stay on
pacer 1.6 (UK, ES, NL) are the holdout that proves the pacer is the cause. Argus must conclude
SUPPORTED_CAUSE on the pacing ratio in DE or FR, citing the pacer rollout.

Randomised per seed: the rollout day (live day 2 or 3, shortly before midnight) and the burn-out time
(09:00..11:00, with a different jitter per budget line and day).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from mockmart.sim import TruthEvent, WorldParams

ROOT_NODE = "pacing_ratio"
COUNTRIES = ("DE", "FR")
NEW_PACER = "1.7"
DEPLOY_ID = "dep_ad-pacer_1.7.0"
QUIET_LIVE_DAYS = 2
AFFECTED_NODES = [
    "pacing_ratio",
    "ad_spend",
    "ad_impressions",
    "ad_clicks",
    "ad_conversions",
    "attributed_gmv",
    "cpa",
    "roas",
    "impressions_per_session",
]


def _front_loaded_share(plan_share_day: np.ndarray, burn_hour: float) -> np.ndarray:
    """Delivered share per hour of the day: traffic-shaped until the budget runs out at `burn_hour`."""
    last = int(burn_hour)
    weights = plan_share_day.copy()
    weights[last] *= burn_hour - last
    weights[last + 1 :] = 0.0
    return weights / weights.sum()


def apply_s4(params: WorldParams, rng: np.random.Generator) -> None:
    cfg = params.cfg
    lines = params.ad_lines
    hit = lines.index[lines.country.isin(COUNTRIES)].to_numpy()

    day0 = cfg.live_start + timedelta(days=QUIET_LIVE_DAYS + int(rng.integers(0, 2)))
    deploy_ts = day0 - timedelta(minutes=int(rng.integers(10, 50)))
    burn_center = float(rng.uniform(9.0, 11.0))
    first_h = params.hour_index(day0)
    for day_start in range(first_h, cfg.hours, 24):
        plan_day = params.ad_plan_share[day_start : day_start + 24]
        for line_idx in hit:
            burn = float(np.clip(burn_center + rng.normal(0.0, 0.3), 8.0, 12.0))
            share = _front_loaded_share(plan_day, burn)
            params.ad_delivery[day_start : day_start + 24, line_idx] *= share / plan_day

    params.add_log(
        "log_deploys",
        {
            "id": DEPLOY_ID,
            "ts": deploy_ts,
            "kind": "deploy",
            "scope": {"country": list(COUNTRIES)},
            "description": "ad-pacer 1.7.0 rolled out for the DE and FR budget lines (faster intraday pacing)",
            "service": "ad-pacer",
            "version": "1.7.0",
        },
    )
    pacer_ids = []
    for line_idx in hit:
        line = lines.loc[line_idx]
        log_id = f"pacer_{line.advertiser_id}_{line.country}_{NEW_PACER}"
        pacer_ids.append(log_id)
        params.add_log(
            "log_ad_budgets",
            {
                "id": log_id,
                "ts": deploy_ts,
                "kind": "pacer_change",
                "scope": {"advertiser_id": [line.advertiser_id], "country": [line.country]},
                "description": f"{line['name']} {line.country}: pacer 1.6 -> {NEW_PACER}",
                "advertiser_id": line.advertiser_id,
                "country": line.country,
                "daily_budget": float(line.base_budget),
                "pacer_version": NEW_PACER,
            },
        )
    params.truth.append(
        TruthEvent(
            event_id="s4_pacer_overburn",
            scenario="s4",
            kind="fault",
            start_ts=day0,
            end_ts=None,
            root_node=ROOT_NODE,
            segment={},
            magnitude={"burn_hour": round(burn_center, 2), "budget_lines": float(len(hit))},
            description=f"pacer {NEW_PACER} spends DE/FR budgets by about {burn_center:.1f}h; UK/ES/NL stay on 1.6",
            expected={
                "verdict": "SUPPORTED_CAUSE",
                "root_node": ROOT_NODE,
                "root_nodes_any": [ROOT_NODE, "ad_spend"],
                "segment": {},
                "segments_any": [{"country": c} for c in COUNTRIES],
                "evidence": DEPLOY_ID,
                "evidence_any": [DEPLOY_ID, *pacer_ids],
                "ruled_out": [],
                "affected_nodes": list(AFFECTED_NODES),
                "max_detection_delay_hours": 4,
            },
        )
    )
