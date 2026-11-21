"""Hidden ground truth. Written next to the world, read only by the bench.

Argus never receives the path to truth.duckdb (a test enforces this). That is what makes the
claim "it could not have peeked" true.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from mockmart.sim import TruthEvent, WorldConfig

TRUTH_SCHEMA = """
CREATE TABLE injected_events (
    event_id VARCHAR, scenario VARCHAR, kind VARCHAR, start_ts TIMESTAMP, end_ts TIMESTAMP,
    root_node VARCHAR, segment JSON, magnitude JSON, description VARCHAR, expected JSON
);
CREATE TABLE world_params (key VARCHAR, value VARCHAR);
"""


def write_truth(path: Path, scenario: str, cfg: WorldConfig, events: list[TruthEvent]) -> None:
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    try:
        con.execute(TRUTH_SCHEMA)
        rows = pd.DataFrame(
            [
                {
                    "event_id": e.event_id,
                    "scenario": e.scenario,
                    "kind": e.kind,
                    "start_ts": e.start_ts,
                    "end_ts": e.end_ts,
                    "root_node": e.root_node,
                    "segment": json.dumps(e.segment, sort_keys=True),
                    "magnitude": json.dumps(e.magnitude, sort_keys=True),
                    "description": e.description,
                    "expected": json.dumps(e.expected, sort_keys=True),
                }
                for e in events
            ],
            columns=[
                "event_id",
                "scenario",
                "kind",
                "start_ts",
                "end_ts",
                "root_node",
                "segment",
                "magnitude",
                "description",
                "expected",
            ],
        )
        if len(rows):
            con.register("_truth", rows)
            con.execute("INSERT INTO injected_events SELECT * FROM _truth")
        params = {"scenario": scenario, "seed": cfg.seed, "start": cfg.start, "days": cfg.days}
        con.executemany("INSERT INTO world_params VALUES (?, ?)", [(k, str(v)) for k, v in params.items()])
    finally:
        con.close()


def read_truth(path: Path) -> list[dict[str, Any]]:
    """Bench-side reader."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        cur = con.execute("SELECT * FROM injected_events ORDER BY start_ts")
        cols = [d[0] for d in cur.description]
        out = []
        for row in cur.fetchall():
            rec = dict(zip(cols, row, strict=True))
            for key in ("segment", "magnitude", "expected"):
                rec[key] = json.loads(rec[key]) if rec[key] else {}
            out.append(rec)
        return out
    finally:
        con.close()
