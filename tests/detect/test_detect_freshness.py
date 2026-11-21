"""Freshness gate against a tiny world that only has an ingestion log."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from argus.contracts.world import render_schema_sql
from argus.detect.freshness import FreshnessGate
from argus.semantic.runner import Runner

ORDERS = "fact_orders_hourly"
SESSIONS = "fact_funnel_hourly"
SHARES = (0.55, 0.25, 0.15, 0.05)
LAGS_MIN = (5, 20, 40, 55)
T0 = datetime(2026, 11, 20, 0)
LATE = T0 + timedelta(hours=10)


def build(path: Path) -> Path:
    """Two days of normal delivery for two tables, except batches 1..3 of ORDERS at LATE arrive 4 h late."""
    con = duckdb.connect(str(path))
    con.execute(render_schema_sql())
    rows = []
    for table in (ORDERS, SESSIONS):
        for h in range(-24, 24):
            ts = T0 + timedelta(hours=h)
            for batch, (share, lag) in enumerate(zip(SHARES, LAGS_MIN, strict=True)):
                delay = timedelta(hours=4) if table == ORDERS and ts == LATE and batch > 0 else timedelta(0)
                rows.append((table, ts, batch, share, ts + timedelta(hours=1, minutes=lag) + delay))
    con.executemany("INSERT INTO raw_ingestion VALUES (?, ?, ?, ?, ?)", rows)
    con.close()
    return path


@pytest.fixture
def gate(tmp_path: Path) -> FreshnessGate:
    return FreshnessGate(Runner(build(tmp_path / "world.duckdb")), [ORDERS, SESSIONS], lookback_hours=12)


def check(gate: FreshnessGate, scored_hour: datetime):
    return gate.check(scored_hour + timedelta(hours=2), scored_hour)


def test_complete_hours_are_ok(gate: FreshnessGate) -> None:
    state = check(gate, LATE - timedelta(hours=1))
    assert state.complete([ORDERS, SESSIONS], state.hour)
    assert state.settled_through == {ORDERS: state.hour, SESSIONS: state.hour}
    assert [f.status for f in state.table_freshness([ORDERS, SESSIONS])] == ["ok", "ok"]
    assert state.went_late == [] and state.caught_up == []


def test_a_late_table_holds_its_nodes_and_is_reported_once(gate: FreshnessGate) -> None:
    check(gate, LATE - timedelta(hours=1))
    state = check(gate, LATE)
    assert state.of(ORDERS, LATE) == pytest.approx(0.55)
    assert not state.complete([ORDERS], LATE) and state.complete([SESSIONS], LATE)
    assert state.confidence([ORDERS, SESSIONS], LATE) == pytest.approx(0.55)
    assert state.went_late == [ORDERS]
    assert state.settled_through[ORDERS] == LATE - timedelta(hours=1)
    assert state.table_freshness([ORDERS])[0].status == "pending"

    later = check(gate, LATE + timedelta(hours=2))
    assert later.went_late == []  # still late, not reported again
    assert later.late_hours[ORDERS] == [LATE]
    assert later.settled_through[ORDERS] == LATE - timedelta(hours=1)  # the later complete hours wait in order

    back = check(gate, LATE + timedelta(hours=4))
    assert back.caught_up == [ORDERS]
    assert back.settled_through[ORDERS] == back.hour


def test_hours_without_any_batch_are_incomplete(gate: FreshnessGate) -> None:
    state = check(gate, T0 + timedelta(hours=30))
    assert state.of(ORDERS, state.hour) == 0.0
    assert ORDERS in state.went_late
