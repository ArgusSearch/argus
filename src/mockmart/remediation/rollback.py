"""`rollback_pacer`: put the requested budget lines back on pacer 1.6 from a budget-day boundary on.

The simulator rebuilds the world's causal parameters from its private configuration (truth.duckdb's
`world_params` and the public manifest), checks that they reproduce the world it was handed, then re-draws
only the ads rows of the rolled-back lines from the effective hour on. Nothing else in the world changes.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from argus.contracts.world import COUNTRIES, raw_columns, table
from mockmart.background import add_background_logs
from mockmart.delivery import _log_frame, split_batches
from mockmart.scenarios import SCENARIOS
from mockmart.sim import WorldConfig, WorldParams, _sample_ads, base_params

REQUEST_VERSION = "remediation-request/1"
RESULT_VERSION = "remediation-result/1"
RESULT_FILE = "remediation.json"
ACTIONS = ("rollback_pacer",)
BASE_PACER = "1.6"
ADS_TABLE = "fact_ads_hourly"
WORLD_FILES = ("world.duckdb", "manifest.json", "truth.duckdb")
_ACTION_ID = re.compile(r"act_[0-9]{4,}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{16,64}")
HOUR = timedelta(hours=1)


class RemediationError(ValueError):
    """The request is invalid or the world cannot carry it. Nothing was written to the output."""


@dataclass(frozen=True)
class RemediationRequest:
    action: str
    world: Path
    out: Path
    countries: tuple[str, ...]
    to_version: str
    effective_at: datetime
    decided_at: datetime
    action_id: str
    digest: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RemediationRequest:
        expected = {
            "version",
            "action",
            "world",
            "out",
            "countries",
            "to_version",
            "effective_at",
            "decided_at",
            "action_id",
            "digest",
        }
        if set(data) != expected:
            raise RemediationError(f"request fields must be exactly {sorted(expected)}")
        if data["version"] != REQUEST_VERSION:
            raise RemediationError(f"unsupported request version {data['version']!r}")
        if data["action"] not in ACTIONS:
            raise RemediationError(f"unknown action {data['action']!r}; known: {list(ACTIONS)}")
        countries = data["countries"]
        if not isinstance(countries, list) or not countries or any(c not in COUNTRIES for c in countries):
            raise RemediationError(f"countries must be a non-empty subset of {list(COUNTRIES)}")
        if len(set(countries)) != len(countries):
            raise RemediationError("countries must not repeat")
        if data["to_version"] != BASE_PACER:
            raise RemediationError(f"rollback_pacer restores pacer {BASE_PACER} only")
        try:
            effective_at = datetime.fromisoformat(data["effective_at"])
            decided_at = datetime.fromisoformat(data["decided_at"])
        except (TypeError, ValueError) as exc:
            raise RemediationError("effective_at and decided_at must be ISO timestamps") from exc
        if effective_at.tzinfo is not None or decided_at.tzinfo is not None:
            raise RemediationError("times are naive UTC")
        if effective_at != effective_at.replace(hour=0, minute=0, second=0, microsecond=0):
            raise RemediationError("effective_at must be a budget-day boundary (00:00)")
        if decided_at > effective_at:
            raise RemediationError("the decision must precede the effective hour: the past cannot change")
        if not _ACTION_ID.fullmatch(str(data["action_id"])) or not _DIGEST.fullmatch(str(data["digest"])):
            raise RemediationError("action_id or digest is malformed")
        return cls(
            action=data["action"],
            world=Path(data["world"]),
            out=Path(data["out"]),
            countries=tuple(sorted(countries)),
            to_version=data["to_version"],
            effective_at=effective_at,
            decided_at=decided_at,
            action_id=str(data["action_id"]),
            digest=str(data["digest"]),
        )


def _world_config(world: Path) -> tuple[str, WorldConfig]:
    """The scenario and configuration that generated `world` (simulator-private; Argus never reads truth)."""
    truth, manifest_path = world / "truth.duckdb", world / "manifest.json"
    if not truth.exists() or not manifest_path.exists():
        raise RemediationError("the world has no simulator configuration (truth.duckdb and manifest.json)")
    con = duckdb.connect(str(truth), read_only=True)
    try:
        values = dict(con.execute("SELECT key, value FROM world_params").fetchall())
    finally:
        con.close()
    manifest = json.loads(manifest_path.read_text())
    start = datetime.fromisoformat(manifest["world_start"])
    end = datetime.fromisoformat(manifest["world_end"])
    live_start = datetime.fromisoformat(manifest["live_start"])
    if datetime.fromisoformat(values["start"]) != start or int(values["days"]) != (end - start).days:
        raise RemediationError("the world's manifest and its simulator configuration disagree")
    cfg = WorldConfig(seed=int(values["seed"]), start=start, days=(end - start).days, live_days=(end - live_start).days)
    return values["scenario"], cfg


def _params(scenario: str, cfg: WorldConfig) -> tuple[WorldParams, np.ndarray]:
    """The world's parameters and its ad delivery before the scenario intervened (same order as `generate`)."""
    if scenario not in SCENARIOS:
        raise RemediationError(f"unknown scenario {scenario!r}")
    world_rng, scenario_rng, _ = (np.random.default_rng(s) for s in np.random.SeedSequence(cfg.seed).spawn(3))
    params = base_params(cfg, world_rng)
    add_background_logs(params, scenario_rng)
    before = params.ad_delivery.copy()
    SCENARIOS[scenario](params, scenario_rng)
    return params, before


def _check_reproduces(params: WorldParams, world: Path) -> None:
    """The rebuilt parameters must name exactly the deploys and pacer changes the world holds."""
    con = duckdb.connect(str(world / "world.duckdb"), read_only=True)
    try:
        for log in ("log_deploys", "log_ad_budgets"):
            held = sorted(con.execute(f"SELECT id, ts FROM {table(log).raw_name}").fetchall())
            rebuilt = sorted((row["id"], row["ts"]) for row in params.logs.get(log, []))
            if held != rebuilt:
                raise RemediationError(f"the world's {log} does not match its configuration")
    finally:
        con.close()


def _pacer_in_force(params: WorldParams, at: datetime) -> dict[tuple[str, str], str]:
    rows = sorted(
        (r for r in params.logs.get("log_ad_budgets", []) if r.get("pacer_version") and r["ts"] < at),
        key=lambda r: r["ts"],
    )
    return {(r["advertiser_id"], r["country"]): r["pacer_version"] for r in rows}


def _rng(cfg: WorldConfig, req: RemediationRequest) -> np.random.Generator:
    """Seeded by the world and the action's typed content only, so the same approval draws the same future."""
    key = json.dumps([req.action, list(req.countries), req.to_version, req.effective_at.isoformat()])
    words = np.frombuffer(hashlib.sha256(key.encode()).digest()[:16], dtype=np.uint32)
    return np.random.default_rng(np.random.SeedSequence([cfg.seed, *(int(w) for w in words)]))


def _log_rows(req: RemediationRequest, params: WorldParams, lines: pd.DataFrame, at: int) -> dict[str, list[dict]]:
    countries = sorted(set(lines.country))
    where = " and ".join(countries)
    deploy = {
        "id": f"dep_ad-pacer_1.6.0_rollback_{req.action_id}",
        "ts": req.effective_at,
        "kind": "deploy",
        "scope": {"country": countries},
        "description": f"ad-pacer rolled back to 1.6.0 for the {where} budget lines (operator approved)",
        "service": "ad-pacer",
        "version": "1.6.0",
    }
    budgets = [
        {
            "id": f"pacer_{line.advertiser_id}_{line.country}_{BASE_PACER}_{req.action_id}",
            "ts": req.effective_at,
            "kind": "pacer_change",
            "scope": {"advertiser_id": [line.advertiser_id], "country": [line.country]},
            "description": f"{line['name']} {line.country}: pacer {line.from_version} -> {BASE_PACER} (rollback)",
            "advertiser_id": line.advertiser_id,
            "country": line.country,
            "daily_budget": float(params.ad_budget[at, int(line.idx)]),
            "pacer_version": BASE_PACER,
        }
        for _, line in lines.iterrows()
    ]
    return {"log_deploys": [deploy], "log_ad_budgets": budgets}


def apply(req: RemediationRequest) -> dict[str, Any]:
    """Write the treated world into `req.out` and return the execution manifest (also `remediation.json`)."""
    if req.action not in ACTIONS:
        raise RemediationError(f"unknown action {req.action!r}")
    if (req.world / RESULT_FILE).exists():
        raise RemediationError("the world is already a remediated branch; apply actions to the factual world")
    if req.out.exists() and any(req.out.iterdir()):
        raise RemediationError("the output directory must be empty")
    scenario, cfg = _world_config(req.world)
    params, before = _params(scenario, cfg)
    _check_reproduces(params, req.world)
    at = params.hour_index(req.effective_at)
    if not 0 < at < cfg.hours:
        raise RemediationError("the effective hour lies outside the world")

    pacer = _pacer_in_force(params, req.effective_at)
    lines = params.ad_lines.reset_index().rename(columns={"index": "idx"})
    keys = zip(lines.advertiser_id, lines.country, strict=True)
    lines["from_version"] = [pacer.get(key, BASE_PACER) for key in keys]
    target = lines[lines.country.isin(req.countries) & (lines.from_version != req.to_version)].reset_index(drop=True)

    deleted = inserted = 0
    logs: dict[str, list[dict]] = {}
    raw = pd.DataFrame()
    if len(target):
        idx = target.idx.to_numpy()
        future = replace(
            params,
            hours=params.hours[at:],
            ad_lines=params.ad_lines.iloc[idx].reset_index(drop=True),
            ad_budget=params.ad_budget[at:, idx],
            ad_plan_share=params.ad_plan_share[at:],
            ad_delivery=before[at:, idx],
        )
        rng = _rng(cfg, req)
        ads, _plan = _sample_ads(future, rng)
        raw, _ingestion = split_batches(ADS_TABLE, ads, params, rng)
        raw = raw[[c.name for c in raw_columns(table(ADS_TABLE))]]
        logs = _log_rows(req, params, target, at)

    req.out.mkdir(parents=True, exist_ok=True)
    for name in WORLD_FILES:
        shutil.copyfile(req.world / name, req.out / name)
    con = duckdb.connect(str(req.out / "world.duckdb"))
    try:
        if len(target):
            ads_raw = table(ADS_TABLE).raw_name
            con.register("_targets", target[["advertiser_id", "country"]])
            gone = con.execute(
                f"DELETE FROM {ads_raw} AS r WHERE r.ts >= ? AND EXISTS (SELECT 1 FROM _targets t "
                "WHERE t.advertiser_id = r.advertiser_id AND t.country = r.country)",
                [req.effective_at],
            ).fetchone()
            deleted = int(gone[0]) if gone else 0
            con.unregister("_targets")
            con.register("_rows", raw)
            cols = ", ".join(raw.columns)
            con.execute(f"INSERT INTO {ads_raw} ({cols}) SELECT {cols} FROM _rows")
            con.unregister("_rows")
            inserted = len(raw)
            for log, rows in logs.items():
                frame = _log_frame(log, rows)
                con.register("_log", frame)
                cols = ", ".join(frame.columns)
                con.execute(f"INSERT INTO {table(log).raw_name} ({cols}) SELECT {cols} FROM _log")
                con.unregister("_log")
        con.execute("CHECKPOINT")
    finally:
        con.close()

    result = {
        "version": RESULT_VERSION,
        "action": req.action,
        "action_id": req.action_id,
        "digest": req.digest,
        "effective_at": req.effective_at.isoformat(),
        "decided_at": req.decided_at.isoformat(),
        "countries": list(req.countries),
        "to_version": req.to_version,
        "noop": not len(target),
        "lines": [
            {"advertiser_id": r.advertiser_id, "country": r.country, "from_version": r.from_version}
            for r in target.itertuples()
        ],
        "rows": {"deleted": int(deleted), "inserted": int(inserted)},
        "log_rows": sorted(r["id"] for rows in logs.values() for r in rows),
    }
    (req.out / RESULT_FILE).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result
