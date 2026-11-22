from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from argus.contracts.findings import Anomaly
from argus.contracts.world import render_schema_sql
from argus.graph.store import load_seed_graph
from argus.market import CONTROL_SOURCE, check_control_group
from argus.semantic.runner import Runner

HOUR = datetime(2026, 11, 20, 18)
AS_OF = HOUR + timedelta(hours=2)


@pytest.fixture
def anomaly() -> Anomaly:
    return Anomaly(
        id="an_0001",
        node="sessions",
        direction="down",
        hour=HOUR,
        detected_at=AS_OF,
        onset=HOUR,
        observed=70,
        expected=100,
        band=(94, 106),
        z=-10,
        rule="z_gt_open",
    )


def _world(
    path: Path,
    *,
    de_sessions: int = 70,
    fr_sessions: int = 70,
    control: float = 70.0,
    control_late: bool = False,
    weeks: int = 4,
    complete: bool = True,
) -> Path:
    with duckdb.connect(str(path)) as con:
        con.execute(render_schema_sql())
        con.execute("CREATE TABLE raw_control (ts TIMESTAMP, ingested_at TIMESTAMP, demand_index DOUBLE)")
        con.execute(
            f"CREATE VIEW {CONTROL_SOURCE} AS SELECT ts, demand_index FROM raw_control "
            "WHERE ingested_at <= getvariable('as_of')"
        )
        for week in range(weeks + 1):
            ts = HOUR - timedelta(weeks=week)
            delivered = ts + timedelta(minutes=118)
            con.execute(
                "INSERT INTO raw_funnel_hourly (ts, country, sessions, ingested_at) VALUES (?, 'DE', ?, ?), "
                "(?, 'FR', ?, ?)",
                [ts, 100 if week else de_sessions, delivered, ts, 100 if week else fr_sessions, delivered],
            )
            con.execute(
                "INSERT INTO raw_ingestion VALUES ('fact_funnel_hourly', ?, 0, ?, ?)",
                [ts, 1.0 if week or complete else 0.55, delivered],
            )
            delay = timedelta(hours=3 if control_late and not week else 2)
            con.execute("INSERT INTO raw_control VALUES (?, ?, ?)", [ts, ts + delay, 100.0 if week else control])
    return path


def test_local_shortfall_survives_the_same_market_dip(tmp_path: Path, anomaly: Anomaly) -> None:
    runner = Runner(_world(tmp_path / "world.duckdb", de_sessions=50))
    graph = load_seed_graph()
    try:
        peer = check_control_group(runner, graph, anomaly.model_copy(update={"segment": {"country": "FR"}}), AS_OF)
        local = check_control_group(runner, graph, anomaly.model_copy(update={"segment": {"country": "DE"}}), AS_OF)

        assert peer and peer.verdict == "market"
        assert local and local.verdict == "us"
        assert peer.series[-1].residual_pct == pytest.approx(0.0)
        point = local.series[-1]
        assert point.control_change_pct == pytest.approx(-30.0)
        assert point.metric_change_pct == pytest.approx(-50.0)
        assert point.adjusted_expected == pytest.approx(70.0)
        assert point.residual_pct == pytest.approx(-100 * (1 - 50 / 70))
        assert runner.rerun(local.receipt_id)[1]
    finally:
        runner.close()


@pytest.mark.parametrize(
    ("metric", "control", "expected"),
    [(70, 100.0, "us"), (95, 70.0, "inconclusive"), (70, 50.0, "inconclusive"), (0, 70.0, "us")],
)
def test_directions_and_disagreement(
    tmp_path: Path, anomaly: Anomaly, metric: int, control: float, expected: str
) -> None:
    runner = Runner(_world(tmp_path / "world.duckdb", de_sessions=metric, fr_sessions=metric, control=control))
    try:
        assessment = check_control_group(runner, load_seed_graph(), anomaly, AS_OF)
        assert assessment and assessment.verdict == expected
    finally:
        runner.close()


@pytest.mark.parametrize("problem", [{"control_late": True}, {"weeks": 2}, {"complete": False}, {"control": 0.0}])
def test_incomplete_evidence_never_explains_a_drop(tmp_path: Path, anomaly: Anomaly, problem: dict) -> None:
    runner = Runner(_world(tmp_path / "world.duckdb", **problem))
    try:
        graph = load_seed_graph()
        assert check_control_group(runner, graph, anomaly, AS_OF) is None
        if problem.get("control_late"):
            later = check_control_group(runner, graph, anomaly, AS_OF + timedelta(hours=1))
            assert later and later.verdict == "market"
    finally:
        runner.close()
