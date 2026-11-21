"""Shared fixtures. Worlds are generated once per session into a temporary directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from argus.contracts.graph import Graph
from argus.graph.store import load_seed_graph
from mockmart.sim import WorldConfig
from mockmart.world import WorldPaths, generate

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def graph() -> Graph:
    return load_seed_graph()


@pytest.fixture(scope="session")
def s1_world(tmp_path_factory: pytest.TempPathFactory) -> WorldPaths:
    return generate("s1", WorldConfig(seed=1), tmp_path_factory.mktemp("s1-world"))


@pytest.fixture(scope="session")
def quiet_world(tmp_path_factory: pytest.TempPathFactory) -> WorldPaths:
    return generate("quiet", WorldConfig(seed=3), tmp_path_factory.mktemp("quiet-world"))
