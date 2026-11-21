"""Build a complete world for one scenario and seed: world.duckdb, truth.duckdb and a public manifest."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from argus.contracts import CONTRACT_VERSION
from mockmart.background import add_background_logs
from mockmart.delivery import DELIVERY_LAG_HOURS, write_world
from mockmart.scenarios import SCENARIOS
from mockmart.sim import WorldConfig, base_params, sample
from mockmart.truth import write_truth


@dataclass(frozen=True)
class WorldPaths:
    world: Path
    truth: Path
    manifest: Path


def generate(scenario: str, cfg: WorldConfig, out_dir: Path) -> WorldPaths:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; known: {sorted(SCENARIOS)}")
    started = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    world_rng, scenario_rng, delivery_rng = (
        np.random.default_rng(s) for s in np.random.SeedSequence(cfg.seed).spawn(3)
    )

    params = base_params(cfg, world_rng)
    add_background_logs(params, scenario_rng)
    write_extension = SCENARIOS[scenario](params, scenario_rng)
    tables = sample(params, world_rng)

    paths = WorldPaths(out_dir / "world.duckdb", out_dir / "truth.duckdb", out_dir / "manifest.json")
    counts = write_world(paths.world, tables, params, delivery_rng)
    if write_extension is not None:
        counts.update(write_extension(paths.world))
    write_truth(paths.truth, scenario, cfg, params.truth)
    manifest = {
        "contract_version": CONTRACT_VERSION,
        "world_start": cfg.start.isoformat(),
        "world_end": cfg.end.isoformat(),
        "live_start": cfg.live_start.isoformat(),
        "delivery_lag_hours": DELIVERY_LAG_HOURS,
        "raw_rows": counts,
        "seconds": round(time.perf_counter() - started, 2),
    }
    # The manifest is public (Argus may read it). It never names the scenario.
    paths.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    return paths
