"""Receipts: canonical hashes and reproducible re-runs pinned to as_of."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from argus.semantic.runner import Runner, canonical_hash
from mockmart.world import WorldPaths


def test_canonical_hash_ignores_row_order_and_float_noise() -> None:
    a = canonical_hash([("DE", 1.0000000000001), ("FR", 2.0)])
    b = canonical_hash([("FR", 2.0), ("DE", 1.0)])
    assert a == b and a.startswith("sha256:")


def test_receipt_rerun_matches_even_after_late_data(s1_world: WorldPaths) -> None:
    runner = Runner(s1_world.world)
    live = datetime.fromisoformat(json.loads(s1_world.manifest.read_text())["live_start"])
    hour = live + timedelta(hours=5)
    sql = f"SELECT country, SUM(orders) AS orders FROM fact_orders_hourly WHERE ts = TIMESTAMP '{hour}' GROUP BY ALL"
    _, early = runner.query(sql, hour + timedelta(hours=1, minutes=10))
    _, late = runner.query(sql, hour + timedelta(hours=3))
    assert early.result_hash != late.result_hash, "late batches change the answer"
    new_hash, matches = runner.rerun(early.id)
    assert matches and new_hash == early.result_hash, "pinned as_of reproduces the early receipt"
