from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from argus.agent.types import RunContext
from argus.contracts.graph import Graph
from argus.contracts.world import render_schema_sql
from argus.evidence import EvidenceStore
from argus.semantic.runner import Runner

HOUR = datetime(2026, 11, 20, 18)
AS_OF = HOUR + timedelta(hours=2)


@pytest.fixture
def runner(tmp_path: Path) -> Iterator[Runner]:
    path = tmp_path / "world.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(render_schema_sql())
        con.execute("CREATE TABLE raw_control (ts TIMESTAMP, demand_index DOUBLE)")
        con.execute("CREATE VIEW market_demand_hourly AS SELECT ts, demand_index FROM raw_control")
        for week in range(5):
            ts = HOUR - timedelta(weeks=week)
            delivery = ts + timedelta(minutes=118)
            con.execute(
                "INSERT INTO raw_payments_hourly "
                "(ts, country, platform, provider, payment_attempts, payment_successes, ingested_at) "
                "VALUES (?, 'DE', 'android', 'PayCo', 100, ?, ?), (?, 'FR', 'android', 'PayCo', 100, 90, ?)",
                [ts, 90 if week else 60, delivery, ts, delivery],
            )
            con.execute(
                "INSERT INTO raw_funnel_hourly (ts, country, sessions, ingested_at) VALUES (?, 'DE', ?, ?)",
                [ts, 100 if week else 70, delivery],
            )
            con.execute(
                "INSERT INTO raw_ingestion VALUES ('fact_funnel_hourly', ?, 0, 1.0, ?)",
                [ts, delivery],
            )
            con.execute("INSERT INTO raw_control VALUES (?, ?)", [ts, 100 if week else 70])

        # This batch is delivered after the session clock. It must not change any replay.
        con.execute(
            "INSERT INTO raw_payments_hourly "
            "(ts, country, platform, provider, payment_attempts, payment_successes, ingested_at) "
            "VALUES (?, 'DE', 'android', 'PayCo', 100, 100, ?)",
            [HOUR, AS_OF + timedelta(minutes=1)],
        )
        con.execute(
            "INSERT INTO raw_deploys (id, ts, kind, scope, description, ingested_at) "
            "VALUES ('android_release', ?, 'release', ?, 'Android release', ?)",
            [HOUR - timedelta(minutes=5), '{"platform":["android"]}', HOUR],
        )
    db = Runner(path)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(run_id="run_0001", stream="evidence-tests", through_seq=4, world_revision="factual", as_of=AS_OF)


@pytest.fixture
def store(ctx: RunContext, graph: Graph, runner: Runner) -> EvidenceStore:
    evidence = EvidenceStore()
    evidence.bind(ctx, graph=graph, runner=runner, latest_hour=HOUR)
    return evidence
