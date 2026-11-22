"""Receipts: canonical hashes and reproducible re-runs pinned to as_of."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import duckdb
import pytest

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


def test_cancel_interrupts_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = tmp_path / "world.duckdb"
    duckdb.connect(str(world)).close()
    runner = Runner(world)
    started, interrupted = threading.Event(), threading.Event()
    cursor = Mock()

    def execute(sql: str) -> None:
        if sql == "SELECT 1":
            started.set()
            assert interrupted.wait(5), "the cursor was not interrupted"
            raise duckdb.InterruptException("interrupted")

    cursor.execute.side_effect = execute
    cursor.interrupt.side_effect = interrupted.set
    monkeypatch.setattr(runner, "_cursor", lambda: cursor)
    as_of = datetime(2026, 1, 1)
    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(runner.fetch, "SELECT 1", as_of)
            assert started.wait(5), "the query did not start"
            runner.cancel()
            with pytest.raises(asyncio.CancelledError):
                pending.result(5)
        with pytest.raises(asyncio.CancelledError):
            runner.fetch("SELECT 2", as_of)
    finally:
        runner.close()
