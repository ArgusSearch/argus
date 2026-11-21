"""Shared fixtures: one S1 world (seed 7) generated once per session, the seed graph and the demo metrics."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from argus.contracts.graph import Graph
from argus.graph.store import load_seed_graph
from argus.semantic.runner import Runner
from mockmart.sim import WorldConfig
from mockmart.world import generate


@pytest.fixture(scope="session")
def world(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate("s1", WorldConfig(seed=7), tmp_path_factory.mktemp("world")).world


@pytest.fixture(scope="session")
def as_of() -> datetime:
    return WorldConfig(seed=7).live_start


@pytest.fixture(scope="session")
def runner(world: Path) -> Iterator[Runner]:
    r = Runner(world)
    yield r
    r.close()


@pytest.fixture()
def seed() -> Graph:
    return load_seed_graph()
