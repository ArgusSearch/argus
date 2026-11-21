"""S1 exit criteria, one test each, on three seeds (Stage 1 is done when these pass).

S1: PayCo payment success for Android in DE drops (random onset, duration and size) while an Android
release ships to every country in the same hour. Argus runs over world.duckdb only; the bench grades
its output against truth.duckdb.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench.s1 import S1Run, run_s1

SEEDS = (1, 2, 3)
_RUNS: dict[int, S1Run] = {}

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module", params=SEEDS, ids=lambda s: f"seed{s}")
def s1(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> S1Run:
    seed = request.param
    if seed not in _RUNS:
        _RUNS[seed] = run_s1(seed, Path(tmp_path_factory.mktemp(f"s1-{seed}")))
    return _RUNS[seed]


def _check(run: S1Run, cid: str) -> None:
    c = run.criterion(cid)
    assert c.passed, f"seed {run.seed}: {c.description}: {c.detail}"


def test_supported_cause_payco_de_android(s1: S1Run) -> None:
    _check(s1, "supported_cause")


def test_release_is_ruled_out_by_holdout(s1: S1Run) -> None:
    _check(s1, "release_ruled_out")


def test_detected_within_three_hours(s1: S1Run) -> None:
    _check(s1, "detected_within_3h")


def test_no_alert_in_48_quiet_hours(s1: S1Run) -> None:
    _check(s1, "quiet_hours_silent")


def test_same_problem_reported_once(s1: S1Run) -> None:
    _check(s1, "one_incident")


def test_every_number_has_a_reproducible_receipt(s1: S1Run) -> None:
    _check(s1, "receipts_reproducible")


def test_quiet_world_opens_nothing(tmp_path: Path) -> None:
    from argus.runtime.loop import Runtime
    from mockmart.sim import WorldConfig
    from mockmart.world import generate

    paths = generate("quiet", WorldConfig(seed=5), tmp_path)
    runtime = Runtime(paths.world)
    runtime.run()
    assert not runtime.anomalies and not runtime.book.incidents
