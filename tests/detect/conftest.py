"""Fixtures for the detect tests: MockMart worlds generated once per session, and the seed graph.

Tests may read a world's truth (like the bench does); the watcher itself never sees it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from argus.contracts.graph import Graph
from argus.graph.store import load_seed_graph
from mockmart.background import add_background_logs
from mockmart.delivery import DELIVERY_LAG_HOURS, write_world
from mockmart.scenarios import SCENARIOS
from mockmart.sim import WorldConfig, WorldParams, base_params, sample
from mockmart.truth import read_truth, write_truth

Mutate = Callable[[WorldParams], None]


@dataclass(frozen=True)
class World:
    path: Path
    cfg: WorldConfig
    truth: list[dict[str, Any]]

    @property
    def live_start(self) -> datetime:
        return self.cfg.live_start

    @property
    def end(self) -> datetime:
        """Last as_of at which every hour of the world is complete."""
        return self.cfg.end + timedelta(hours=1)

    def fault(self) -> dict[str, Any]:
        return next(t for t in self.truth if t["kind"] == "fault")


def build_world(out: Path, scenario: str, seed: int, mutate: Mutate | None = None) -> World:
    """Same steps as `mockmart.world.generate`, with an optional extra intervention before sampling."""
    cfg = WorldConfig(seed=seed)
    out.mkdir(parents=True, exist_ok=True)
    world_rng, scenario_rng, delivery_rng = (np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(3))
    params = base_params(cfg, world_rng)
    add_background_logs(params, scenario_rng)
    SCENARIOS[scenario](params, scenario_rng)
    if mutate is not None:
        mutate(params)
    tables = sample(params, world_rng)
    write_world(out / "world.duckdb", tables, params, delivery_rng)
    write_truth(out / "truth.duckdb", scenario, cfg, params.truth)
    manifest = {
        "world_start": cfg.start.isoformat(),
        "world_end": cfg.end.isoformat(),
        "live_start": cfg.live_start.isoformat(),
        "delivery_lag_hours": DELIVERY_LAG_HOURS,
    }
    (out / "manifest.json").write_text(json.dumps(manifest))
    return World(out / "world.duckdb", cfg, read_truth(out / "truth.duckdb"))


@pytest.fixture(scope="session")
def graph() -> Graph:
    return load_seed_graph()


@pytest.fixture(scope="session")
def make_world(tmp_path_factory: pytest.TempPathFactory) -> Callable[..., World]:
    cache: dict[tuple[str, int, str], World] = {}

    def make(scenario: str, seed: int, mutate: Mutate | None = None, tag: str = "") -> World:
        key = (scenario, seed, tag)
        if key not in cache:
            cache[key] = build_world(tmp_path_factory.mktemp(f"{scenario}-{seed}{tag}"), scenario, seed, mutate)
        return cache[key]

    return make
