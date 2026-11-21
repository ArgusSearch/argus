"""Shared fixtures for the bench tests: generated worlds are cached per (scenario, seed) for the session."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from mockmart.sim import WorldConfig
from mockmart.world import WorldPaths, generate

SEEDS = (1, 2, 3)


@pytest.fixture(scope="session")
def world(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str, int], WorldPaths]:
    cache: dict[tuple[str, int], WorldPaths] = {}

    def make(scenario: str, seed: int) -> WorldPaths:
        key = (scenario, seed)
        if key not in cache:
            cache[key] = generate(scenario, WorldConfig(seed=seed), tmp_path_factory.mktemp(f"{scenario}-{seed}"))
        return cache[key]

    return make


class View:
    """Read-only world connection with a movable `as_of`."""

    def __init__(self, path: Path):
        self.con = duckdb.connect(str(path), read_only=True)

    def at(self, as_of: datetime) -> View:
        self.con.execute(f"SET VARIABLE as_of = TIMESTAMP '{as_of:%Y-%m-%d %H:%M:%S}'")
        return self

    def all(self, sql: str) -> list[tuple]:
        return self.con.execute(sql).fetchall()

    def one(self, sql: str) -> tuple:
        row = self.con.execute(sql).fetchone()
        assert row is not None
        return row


@pytest.fixture
def view() -> Iterator[Callable[[Path], View]]:
    opened: list[View] = []

    def open_view(path: Path) -> View:
        v = View(path)
        opened.append(v)
        return v

    yield open_view
    for v in opened:
        v.con.close()
