"""Re-run a receipt's SQL at its pinned `as_of` and compare the result hash ("click the number").

Live mode re-runs through the runtime's own runner. Replay mode needs the world the recording was made
from: `--world`, or a world under `ARGUS_RUNS_DIR` (default `runs/`) whose manifest matches the recorded
one (`make world SEED=1` for the S1 fixtures). Argus never generates worlds itself.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import duckdb
from pydantic import BaseModel, ConfigDict

from argus.contracts.findings import Receipt
from argus.contracts.world import AS_OF_VARIABLE
from argus.graph.store import REPO
from argus.semantic.runner import Runner, canonical_hash, sql_ts


class RerunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt: str
    as_of: datetime
    expected_hash: str
    result_hash: str
    matches: bool
    rows: int
    ms: float
    world: str


class RerunUnavailable(RuntimeError):
    pass


class Rerunner(Protocol):
    def rerun(self, receipt: Receipt) -> RerunResult: ...

    def close(self) -> None: ...


def _comparable(manifest: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in manifest.items() if k != "seconds"}


def find_world(manifest: dict[str, Any], runs: Path | None = None) -> Path | None:
    """A world under `runs` whose manifest equals the recorded one (ignoring generation time)."""
    runs = runs or Path(os.environ.get("ARGUS_RUNS_DIR", str(REPO / "runs")))
    if not manifest or not runs.is_dir():
        return None
    want = _comparable(manifest)
    for path in sorted(runs.glob("*/manifest.json")):
        try:
            if _comparable(json.loads(path.read_text())) == want and (path.parent / "world.duckdb").exists():
                return path.parent / "world.duckdb"
        except (OSError, ValueError):
            continue
    return None


class WorldRerunner:
    """Re-runs receipts against one world file, read-only. The world is resolved on first use."""

    def __init__(self, world: Path | None = None, manifest: dict[str, Any] | None = None) -> None:
        self._world = world
        self._manifest = manifest or {}
        self._con: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()

    def _resolve(self) -> Path:
        if self._world is None:
            self._world = find_world(self._manifest)
        if self._world is None:
            raise RerunUnavailable(
                "re-running needs the world this run was recorded on: `make world SEED=<seed>` "
                "(the S1 fixtures use seed 1), or start the API with --world"
            )
        return self._world

    def rerun(self, receipt: Receipt) -> RerunResult:
        with self._lock:
            world = self._resolve()
            if self._con is None:
                self._con = duckdb.connect(str(world), read_only=True)
            cur = self._con.cursor()
        try:
            started = time.perf_counter()
            cur.execute(f"SET VARIABLE {AS_OF_VARIABLE} = {sql_ts(receipt.as_of)}")
            rows = cur.execute(receipt.sql).fetchall()
            ms = (time.perf_counter() - started) * 1000
        finally:
            cur.close()
        result_hash = canonical_hash(rows)
        return RerunResult(
            receipt=receipt.id,
            as_of=receipt.as_of,
            expected_hash=receipt.result_hash,
            result_hash=result_hash,
            matches=result_hash == receipt.result_hash,
            rows=len(rows),
            ms=round(ms, 2),
            world=world.parent.name or str(world),
        )

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None


class RunnerRerunner:
    """Live mode: re-run through the runtime's runner, which holds the same world open."""

    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    def rerun(self, receipt: Receipt) -> RerunResult:
        started = time.perf_counter()
        rows = self._runner.fetch(receipt.sql, receipt.as_of)
        ms = (time.perf_counter() - started) * 1000
        result_hash = canonical_hash([tuple(r.values()) for r in rows])
        return RerunResult(
            receipt=receipt.id,
            as_of=receipt.as_of,
            expected_hash=receipt.result_hash,
            result_hash=result_hash,
            matches=result_hash == receipt.result_hash,
            rows=len(rows),
            ms=round(ms, 2),
            world=self._runner.world_path.parent.name or str(self._runner.world_path),
        )

    def close(self) -> None:
        pass
