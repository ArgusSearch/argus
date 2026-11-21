"""Observation layer: micro-batch delivery, the ingestion log, and loading into world.duckdb.

Every live hour of a fact table arrives in four micro-batches (55/25/15/5% of the events)
5, 20, 40 and 55 minutes after the hour ends, so the normal delivery lag is under 2 hours.
Scenarios can delay batches 1..3 of chosen hours (a stalled ETL job).
History far before the live window is stored compacted as one batch: it arrived long ago,
so every `as_of` the runtime uses sees it complete, and the world stays small.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from argus.contracts.world import ALL_TABLES, FACT_TABLES, LOG_TABLES, raw_columns, render_schema_sql, table
from mockmart.sim import ADVERTISER_BOOK, WorldParams

BATCH_SHARES = (0.55, 0.25, 0.15, 0.05)
BATCH_LAG_MIN = (5, 20, 40, 55)
DELIVERY_LAG_HOURS = 2  # the newest hour that is complete at as_of T is T - 2h
# Amount measures are split in proportion to the count that drives them.
AMOUNT_DRIVER = {"gmv": "orders", "ad_spend": "ad_clicks", "attributed_gmv": "ad_conversions"}
PLAN_TABLE = "fact_ad_plan_hourly"


def split_batches(
    name: str, df: pd.DataFrame, params: WorldParams, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (raw rows with batch and ingested_at, log_ingestion rows) for one fact table."""
    spec = table(name)
    hour_end = df["ts"] + pd.Timedelta(hours=1)

    if name == PLAN_TABLE:
        raw = df.copy()
        raw["batch"] = 0
        raw["ingested_at"] = df["ts"].dt.floor("D") - pd.Timedelta(days=1)
        return raw, _ingestion_rows(name, raw, share=1.0)

    compact_before = pd.Timestamp(params.cfg.live_start - timedelta(hours=DELIVERY_LAG_HOURS))
    old = df["ts"] < compact_before
    hist = df[old].copy()
    hist["batch"] = 0
    hist["ingested_at"] = hour_end[old] + pd.Timedelta(minutes=BATCH_LAG_MIN[-1])

    live = df[~old].reset_index(drop=True)
    hour_idx = ((live["ts"] - pd.Timestamp(params.cfg.start)) / pd.Timedelta(hours=1)).astype(int).to_numpy()
    delay = params.extra_delay_min.get(name)
    extra = delay[hour_idx] if delay is not None else np.zeros(len(live))

    remaining = {m: live[m].to_numpy().copy() for m in spec.measures}
    drivers_total = {a: live[d].to_numpy() for a, d in AMOUNT_DRIVER.items() if a in remaining}
    parts = []
    left = 1.0
    for b, (share, lag) in enumerate(zip(BATCH_SHARES, BATCH_LAG_MIN, strict=True)):
        part = live.drop(columns=spec.measures).copy()
        taken: dict[str, np.ndarray] = {}
        last = b == len(BATCH_SHARES) - 1
        for m in spec.measures:
            if m in AMOUNT_DRIVER:
                continue
            take = remaining[m] if last else rng.binomial(remaining[m], share / left)
            taken[m] = take
        for m, total_driver in drivers_total.items():
            if last:
                taken[m] = remaining[m]
            else:
                frac = np.divide(
                    taken[AMOUNT_DRIVER[m]], total_driver, out=np.full(len(live), share), where=total_driver > 0
                )
                taken[m] = np.round(live[m].to_numpy() * frac, 2)
        for m in spec.measures:
            part[m] = taken[m]
            remaining[m] = remaining[m] - taken[m]
        left -= share
        part["batch"] = b
        late = extra if b >= 1 else np.zeros(len(live))
        part["ingested_at"] = (
            part["ts"] + pd.Timedelta(hours=1) + pd.Timedelta(minutes=lag) + pd.to_timedelta(late, unit="min")
        )
        parts.append(part)
    raw = pd.concat([hist, *parts], ignore_index=True)

    ing = pd.concat(
        [
            _ingestion_rows(name, hist, share=1.0),
            *[_ingestion_rows(name, p, share=s) for p, s in zip(parts, BATCH_SHARES, strict=True)],
        ],
        ignore_index=True,
    )
    return raw, ing


def _ingestion_rows(name: str, raw: pd.DataFrame, share: float) -> pd.DataFrame:
    first = raw.groupby(["ts", "batch"], as_index=False)["ingested_at"].max()
    first.insert(0, "table_name", name)
    first["share"] = share
    return first[["table_name", "ts", "batch", "share", "ingested_at"]]


_LOG_DEFAULT_LAG = {
    "log_deploys": timedelta(minutes=1),
    "log_provider_status": timedelta(minutes=1),
    "log_calendar": timedelta(days=-7),
    "log_ad_budgets": timedelta(0),
}


def _log_frame(name: str, rows: list[dict[str, Any]]) -> pd.DataFrame:
    spec = table(name)
    cols = [c.name for c in raw_columns(spec)]
    records = []
    for row in rows:
        rec = {c: row.get(c) for c in cols}
        if rec.get("ingested_at") is None:
            rec["ingested_at"] = row["ts"] + _LOG_DEFAULT_LAG[name]
        for json_col in ("scope", "planned_uplift"):
            if json_col in rec:
                rec[json_col] = json.dumps(rec[json_col] if rec[json_col] is not None else {}, sort_keys=True)
        records.append(rec)
    return pd.DataFrame.from_records(records, columns=cols)


def write_world(
    path: Path, tables: dict[str, pd.DataFrame], params: WorldParams, rng: np.random.Generator
) -> dict[str, int]:
    """Create world.duckdb with the C1 schema and load every raw table. Returns row counts."""
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    try:
        con.execute(render_schema_sql())
        counts: dict[str, int] = {}
        ingestion = []
        for spec in FACT_TABLES:
            raw, ing = split_batches(spec.name, tables[spec.name], params, rng)
            _insert(con, spec.raw_name, raw[[c.name for c in raw_columns(spec)]])
            ingestion.append(ing)
            counts[spec.raw_name] = len(raw)
        _insert(con, table("log_ingestion").raw_name, pd.concat(ingestion, ignore_index=True))
        for spec in LOG_TABLES:
            if spec.name == "log_ingestion":
                continue
            frame = _log_frame(spec.name, params.logs.get(spec.name, []))
            if len(frame):
                _insert(con, spec.raw_name, frame)
            counts[spec.raw_name] = len(frame)
        adv = pd.DataFrame(
            [{"advertiser_id": a, "name": b[0], "vertical": b[1]} for a, b in ADVERTISER_BOOK.items()],
        )
        _insert(con, "dim_advertiser", adv)
        assert {s.raw_name for s in ALL_TABLES} <= {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        con.execute("CHECKPOINT")
        return counts
    finally:
        con.close()


def _insert(con: duckdb.DuckDBPyConnection, name: str, frame: pd.DataFrame) -> None:
    con.register("_load", frame)
    try:
        cols = ", ".join(frame.columns)
        con.execute(f"INSERT INTO {name} ({cols}) SELECT {cols} FROM _load")
    finally:
        con.unregister("_load")
