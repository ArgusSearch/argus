"""S3: the orders loader stalls for a few hours, then backfills. Nothing happened to the business.

During the stall only the first micro-batch (55% of the events) of each `fact_orders_hourly` hour
arrives; batches 1..3 come in one backfill after the stall. Payments keep arriving normally, so the
identity orders = payment_successes breaks for exactly the stalled hours, and `log_ingestion` shows the
missing batches. Argus must conclude DATA_ISSUE, open no business incident, and re-check after the
backfill. A checkout-service hotfix deploys just before the stall: the tempting wrong answer.

Randomised per seed: the first stalled hour (at least 48 quiet live hours before it), the stall length
(3..5 hours) and the backfill delay after the stall (10..40 minutes).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from mockmart.delivery import BATCH_LAG_MIN, BATCH_SHARES
from mockmart.sim import TruthEvent, WorldParams

TABLE = "fact_orders_hourly"
ROOT_NODE = "orders"
IDENTITY_EDGE = "f_orders_payments"
QUIET_LIVE_HOURS = 48
# Every node computed from fact_orders_hourly reads wrong while the table is partial.
AFFECTED_NODES = ["orders", "gmv", "cvr", "aov"]
HOTFIX_ID_PREFIX = "dep_checkout-service_hotfix"


def apply_s3(params: WorldParams, rng: np.random.Generator) -> None:
    cfg = params.cfg
    live_h = params.hour_index(cfg.live_start)
    n_hours = int(rng.integers(3, 6))
    onset_h = int(rng.integers(live_h + QUIET_LIVE_HOURS, cfg.hours - 24 - n_hours + 1))
    backfill_min = int(rng.integers(10, 41))

    # Wall clock: the loader stops when the first stalled hour closes and restarts n_hours later.
    stall_start = params.hours[onset_h].to_pydatetime() + timedelta(hours=1)
    stall_end = stall_start + timedelta(hours=n_hours)
    backfill_at = stall_end + timedelta(minutes=backfill_min)
    # delivery.split_batches delays batches 1..3 of an hour by extra_delay_min[hour]; aim batch 1 at the backfill.
    delay = params.extra_delay_min.setdefault(TABLE, np.zeros(cfg.hours))
    for h in range(onset_h, onset_h + n_hours):
        normal_batch1 = params.hours[h].to_pydatetime() + timedelta(hours=1, minutes=BATCH_LAG_MIN[1])
        delay[h] = (backfill_at - normal_batch1) / timedelta(minutes=1)

    t0 = params.hours[onset_h].to_pydatetime()
    t1 = params.hours[onset_h + n_hours].to_pydatetime()
    hotfix_ts = stall_start - timedelta(minutes=int(rng.integers(5, 25)))
    hotfix_id = f"{HOTFIX_ID_PREFIX}_{hotfix_ts:%m%d%H%M}"
    params.add_log(
        "log_deploys",
        {
            "id": hotfix_id,
            "ts": hotfix_ts,
            "kind": "deploy",
            "scope": {},
            "description": "checkout-service hotfix (all users): retry tuning for the order confirmation call",
            "service": "checkout-service",
            "version": "hotfix",
        },
    )
    params.truth.append(
        TruthEvent(
            event_id="s3_orders_loader_stall",
            scenario="s3",
            kind="data",
            start_ts=t0,
            end_ts=t1,
            root_node=ROOT_NODE,
            segment={},
            magnitude={
                "stalled_hours": float(n_hours),
                "completeness_during_stall": BATCH_SHARES[0],
                "backfill_minutes_after_stall": float(backfill_min),
            },
            description=f"{TABLE} delivers only batch 0 for {n_hours} h, backfilled at {backfill_at:%H:%M}",
            expected={
                "verdict": "DATA_ISSUE",
                "root_node": ROOT_NODE,
                "table": TABLE,
                "segment": {},
                "identity": IDENTITY_EDGE,
                "page": False,
                "affected_nodes": list(AFFECTED_NODES),
                "backfill_at": backfill_at.isoformat(),
                "ruled_out": [hotfix_id],
                "max_detection_delay_hours": 3,
            },
        )
    )
    params.truth.append(
        TruthEvent(
            event_id="s3_hotfix_red_herring",
            scenario="s3",
            kind="red_herring",
            start_ts=hotfix_ts,
            end_ts=None,
            root_node=None,
            segment={},
            magnitude={},
            description="checkout-service hotfix right before the stall; it changes no data",
        )
    )
