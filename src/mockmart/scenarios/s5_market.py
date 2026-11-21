"""S5: independent demand falls across the market, then a checkout config introduces a local fault."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from functools import partial
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from argus.contracts.world import AS_OF_VARIABLE
from mockmart.delivery import DELIVERY_LAG_HOURS
from mockmart.sim import SUCCESS_P, TruthEvent, WorldParams

# Feed contract for scenario producers and investigators. See docs/ext/market.md.
CONTROL_SOURCE = "market_demand_hourly"
RAW_CONTROL = f"raw_{CONTROL_SOURCE}"
MARKET_NODES = ("sessions", "orders", "gmv")
FAULT_NODE = "payment_success_rate"
FAULT_SEGMENT = {"country": "DE", "platform": "android", "provider": "PayCo"}
CONFIG_ID = "dep_checkout-routing_retry-policy"


def apply_s5(params: WorldParams, rng: np.random.Generator) -> Callable[[Path], dict[str, int]]:
    cfg = params.cfg
    quiet, recovery = 48, 24
    market_hours = int(rng.integers(12, 17))
    first_onset = params.hour_index(cfg.live_start) + quiet
    last_onset = cfg.hours - recovery - market_hours
    if first_onset > last_onset:
        raise ValueError("S5 needs at least four live days")
    onset = int(rng.integers(first_onset, last_onset + 1))
    market_drop = float(rng.uniform(0.29, 0.37))

    # A shared demand driver acts upstream of both the shop funnel and the independent peer sample.
    demand = rng.lognormal(0, 0.015, cfg.hours)
    demand[onset : onset + market_hours] *= 1 - market_drop
    params.mu_sessions *= demand[:, None]
    feed = pd.DataFrame(
        {
            "ts": params.hours,
            "ingested_at": params.hours + pd.Timedelta(hours=DELIVERY_LAG_HOURS),
            "demand_index": 100 * demand * rng.lognormal(0, 0.012, cfg.hours),
        }
    )

    # The broad drop is visible first. While it continues, an internal routing change adds a rate fault.
    fault_onset = onset + 3
    fault_hours = int(rng.integers(6, 9))
    fault_rate = float(rng.uniform(0.48, 0.58))
    mask = params.seg_mask(country=FAULT_SEGMENT["country"], platform=FAULT_SEGMENT["platform"])
    params.success_p["PayCo"][fault_onset : fault_onset + fault_hours, mask] = fault_rate
    market_start = params.hours[onset].to_pydatetime()
    fault_start = params.hours[fault_onset].to_pydatetime()
    params.add_log(
        "log_deploys",
        {
            "id": CONFIG_ID,
            "ts": fault_start - timedelta(minutes=4),
            "kind": "config",
            "scope": {name: [value] for name, value in FAULT_SEGMENT.items()},
            "description": "Checkout routing enabled a shorter retry timeout for PayCo on Android in Germany",
            "service": "checkout-routing",
            "version": "retry-policy",
        },
    )
    params.truth.extend(
        [
            TruthEvent(
                event_id="s5_market_dip",
                scenario="s5",
                kind="innocent",
                start_ts=market_start,
                end_ts=market_start + timedelta(hours=market_hours),
                root_node="sessions",
                segment={},
                magnitude={"demand_drop": market_drop},
                description="External market demand declines across peer shops and MockMart.",
                expected={
                    "verdict": "EXPECTED",
                    "root_node": "sessions",
                    "affected_nodes": list(MARKET_NODES),
                    "evidence": CONTROL_SOURCE,
                    "page": False,
                },
            ),
            TruthEvent(
                event_id="s5_checkout_routing_fault",
                scenario="s5",
                kind="fault",
                start_ts=fault_start,
                end_ts=fault_start + timedelta(hours=fault_hours),
                root_node=FAULT_NODE,
                segment=dict(FAULT_SEGMENT),
                magnitude={"success_rate_normal": SUCCESS_P["PayCo"], "success_rate_fault": fault_rate},
                description="MockMart's checkout routing change reduces payment success in the rollout segment.",
                expected={
                    "verdict": "SUPPORTED_CAUSE",
                    "root_node": FAULT_NODE,
                    "affected_nodes": [FAULT_NODE, "cvr"],
                    "evidence": CONFIG_ID,
                    "max_detection_delay_hours": DELIVERY_LAG_HOURS + 1,
                },
            ),
        ]
    )
    return partial(_write_control_feed, feed=feed)


def _write_control_feed(world: Path, *, feed: pd.DataFrame) -> dict[str, int]:
    with duckdb.connect(str(world)) as con:
        con.execute(
            f"""
            CREATE TABLE {RAW_CONTROL} (
                ts TIMESTAMP PRIMARY KEY,
                ingested_at TIMESTAMP NOT NULL,
                demand_index DOUBLE NOT NULL
            );
            """
        )
        con.register("_s5_feed", feed)
        con.execute(f"INSERT INTO {RAW_CONTROL} SELECT ts, ingested_at, demand_index FROM _s5_feed")
        con.execute(
            f"""
            CREATE VIEW {CONTROL_SOURCE} AS
            SELECT ts, demand_index FROM {RAW_CONTROL} WHERE ingested_at <= getvariable('{AS_OF_VARIABLE}')
            """
        )
    return {RAW_CONTROL: len(feed)}
