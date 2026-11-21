"""Freshness gate: late data is a data problem, never a business page."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from argus.runtime.loop import Runtime
from mockmart.world import WorldPaths


def test_late_table_is_pending_and_logged_as_data_issue(s1_world: WorldPaths, tmp_path: Path) -> None:
    world = tmp_path / "world.duckdb"
    shutil.copy(s1_world.world, world)
    shutil.copy(s1_world.manifest, tmp_path / "manifest.json")
    live = datetime.fromisoformat(json.loads(s1_world.manifest.read_text())["live_start"])
    stall_start, stall_end = live + timedelta(hours=10), live + timedelta(hours=12)
    con = duckdb.connect(str(world))
    window = f"ts BETWEEN TIMESTAMP '{stall_start}' AND TIMESTAMP '{stall_end}'"
    con.execute(
        f"UPDATE raw_orders_hourly SET ingested_at = ingested_at + INTERVAL 4 HOUR WHERE batch >= 1 AND {window}"
    )
    con.execute(
        "UPDATE raw_ingestion SET ingested_at = ingested_at + INTERVAL 4 HOUR "
        f"WHERE table_name = 'fact_orders_hourly' AND batch >= 1 AND {window}"
    )
    con.close()

    runtime = Runtime(world)
    ticks = [live + timedelta(hours=h + 2) for h in range(8, 16)]
    runtime.run(ticks)
    pending = {
        e.payload["hour"]: set(e.payload["pending_nodes"]) for e in runtime.bus.history if e.type.value == "tick"
    }
    stalled_hour = stall_start.isoformat()
    assert {"orders", "gmv", "cvr"} <= pending[stalled_hour]
    assert "payment_success_rate" not in pending[stalled_hour], "unaffected tables keep being scored"
    notes = [n for n in runtime.book.notes if n.kind == "data_issue"]
    assert len(notes) == 1 and "fact_orders_hourly" in notes[0].reason
    assert not runtime.anomalies and not runtime.book.incidents
