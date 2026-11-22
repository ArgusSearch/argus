"""Run the one fixed simulator command across the process boundary and switch a runner to its output.

Argus never imports the simulator: like the counterfactual replay (`argus.counterfactual.replay`), it calls
`python -m mockmart.remediation apply --request <file>` with a request it wrote itself and reads only the
treated world.duckdb and its public execution manifest. The branch is built in a staging directory and
published with one atomic rename, so a crash leaves either no branch or a complete one; a retry with the same
digest reuses the published branch.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from argus.semantic.runner import Runner

REQUEST_VERSION = "remediation-request/1"
RESULT_FILE = "remediation.json"
TIMEOUT_SECONDS = 180


class ExecutionFailed(RuntimeError):
    """The simulator refused or failed the request; nothing was published."""


@dataclass(frozen=True)
class Branch:
    path: Path  # directory holding world.duckdb, manifest.json and remediation.json
    result: dict[str, Any]

    @property
    def world(self) -> Path:
        return self.path / "world.duckdb"


def branch_dir(root: Path, proposal_id: str, digest: str) -> Path:
    return root / f"{proposal_id}-{digest.removeprefix('sha256:')[:12]}"


def _published(path: Path, proposal_id: str, digest: str) -> Branch | None:
    result_file = path / RESULT_FILE
    if not result_file.exists():
        return None
    result = json.loads(result_file.read_text())
    if result.get("action_id") != proposal_id or result.get("digest") != digest:
        raise ExecutionFailed(f"{path} holds a different action; refusing to reuse it")
    return Branch(path, result)


def execute(
    root: Path,
    *,
    world: Path,
    proposal_id: str,
    digest: str,
    countries: list[str],
    to_version: str,
    effective_at: datetime,
    decided_at: datetime,
) -> Branch:
    """Build (or reuse) the treated branch for one approved proposal. Idempotent per (proposal, digest)."""
    final = branch_dir(root, proposal_id, digest)
    found = _published(final, proposal_id, digest)
    if found is not None:
        return found
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{proposal_id}-{uuid.uuid4().hex[:8]}"
    request = root / f".request-{proposal_id}-{uuid.uuid4().hex[:8]}.json"
    request.write_text(
        json.dumps(
            {
                "version": REQUEST_VERSION,
                "action": "rollback_pacer",
                "world": str(world.parent),
                "out": str(staging),
                "countries": sorted(countries),
                "to_version": to_version,
                "effective_at": effective_at.isoformat(),
                "decided_at": decided_at.isoformat(),
                "action_id": proposal_id,
                "digest": digest,
            },
            indent=2,
        )
    )
    command = [sys.executable, "-m", "mockmart.remediation", "apply", "--request", str(request)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        if done.returncode != 0:
            try:
                reason = json.loads(done.stdout.strip().splitlines()[-1])["error"]
            except (IndexError, KeyError, ValueError):
                reason = (done.stderr.strip().splitlines() or ["no output"])[-1]
            raise ExecutionFailed(f"the simulator refused the action: {reason}")
        try:
            staging.rename(final)
        except OSError:
            # Another worker published the same branch first: keep theirs.
            if _published(final, proposal_id, digest) is None:
                raise
    except subprocess.TimeoutExpired as exc:
        raise ExecutionFailed("the simulator did not finish in time") from exc
    finally:
        request.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
    found = _published(final, proposal_id, digest)
    if found is None:
        raise ExecutionFailed("the simulator wrote no execution manifest")
    return found


def switch_world(runner: Runner, world: Path) -> None:
    """Point a live `Runner` at another world file, read-only, keeping its receipts and receipt counter.

    The detector, edge tester, watcher and incident book all hold the same `Runner`, so they follow together.
    Call it under the runtime lock (between ticks): queries in flight on other threads would lose their cursor.
    Receipts minted before the switch re-run to the same hash on a treated branch, whose past is unchanged.
    """
    fresh = duckdb.connect(str(world), read_only=True)
    lock: threading.Lock = runner._lock
    with lock:
        old = runner._con
        runner._con = fresh
        runner._local = threading.local()
        runner.world_path = Path(world)
    old.close()
