from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from argus.contracts.world import render_schema_sql
from argus.evidence.sqlgate import run_check, validate
from argus.semantic.runner import Runner

AS_OF = datetime(2026, 11, 20, 2)
PREDICT = {"value": "rate", "group": "provider", "a": ["PayCo"], "b": "rest", "relation": "a_lt_b", "min_gap": 0.1}
CUT = """SELECT provider, SUM(payment_successes)::DOUBLE / NULLIF(SUM(payment_attempts), 0) AS rate
FROM fact_payments_hourly WHERE country = 'DE' AND platform = 'android' GROUP BY provider"""


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("sqlgate") / "world.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(render_schema_sql())
        con.execute(
            "INSERT INTO raw_payments_hourly VALUES (?, 'DE', 'android', ?, 100, ?, 0, ?)",
            [AS_OF - timedelta(hours=1), "PayCo", 70, AS_OF],
        )
        con.execute(
            "INSERT INTO raw_payments_hourly VALUES (?, 'DE', 'android', ?, 100, ?, 0, ?)",
            [AS_OF - timedelta(hours=1), "CardHub", 99, AS_OF],
        )
        con.execute(
            "INSERT INTO raw_payments_hourly VALUES (?, 'DE', 'android', ?, 100, ?, 0, ?)",
            [AS_OF + timedelta(hours=1), "PayCo", 100, AS_OF + timedelta(hours=2)],
        )
        con.execute(
            "INSERT INTO raw_orders_hourly "
            "SELECT ? - n * INTERVAL '1 hour', 'DE', 'android', 'paid', 'home', 10, 50, 0, ? FROM range(205) r(n)",
            [AS_OF, AS_OF],
        )
    return path


@pytest.fixture
def runner(database: Path) -> Iterator[Runner]:
    r = Runner(database)
    try:
        yield r
    finally:
        r.close()


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE new AS SELECT 1",
        "UPDATE dim_advertiser SET name = 'changed'",
        "SELECT 1; SELECT 2",
        "SELECT * FROM raw_payments_hourly",
        "SELECT * FROM main.fact_payments_hourly",
        'SELECT * FROM "fact_payments_hourly "',
        "WITH FACT_PAYMENTS_HOURLY AS (SELECT 1) SELECT * FROM FACT_PAYMENTS_HOURLY",
        "SELECT * FROM read_csv('x.csv')",
        "SELECT * FROM read_parquet('x.parquet')",
        "SELECT * FROM glob('*.csv')",
        "SELECT * FROM range(3)",
        "ATTACH 'truth.duckdb' AS truth",
        "COPY (SELECT 1) TO 'out.csv'",
        "PRAGMA show_tables",
        "SET VARIABLE as_of = TIMESTAMP '2070-01-01'",
        "SELECT getvariable('as_of')",
        "LOAD parquet",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM duckdb_tables()",
        "SELECT * FROM truth_events",
        "WITH RECURSIVE r AS (SELECT 1) SELECT * FROM r",
        "SELECT * FROM fact_payments_hourly CROSS JOIN log_deploys",
        "SELECT * FROM fact_payments_hourly JOIN fact_orders_hourly USING (ts)",
        "SELECT /* comment */ COUNT(*) FROM log_events",
        "EXPLAIN SELECT * FROM fact_payments_hourly",
        "CALL dbgen()",
        "SELECT 1" + " " * 2000,
        "WITH raw_payments_hourly AS (SELECT 1) SELECT (SELECT x FROM raw_orders_hourly)",
        "SELECT * FROM (WITH x AS (SELECT * FROM raw_payments_hourly) SELECT * FROM x)",
        "SELECT try_cast('1' AS INTEGER)",
        "SELECT * FROM fact_ads_hourly a JOIN fact_ads_hourly b USING (ts, advertiser_id, country, platform)",
        "SELECT 1 UNION ALL SELECT 2",
    ],
)
def test_rejected_queries_never_reach_runner(runner: Runner, sql: str) -> None:
    judgement = validate(sql)
    assert not judgement.accepted and judgement.rule
    assert run_check(runner, sql, AS_OF, PREDICT, "comparison") == judgement
    assert runner.query_count == 0


@pytest.mark.parametrize(
    "sql",
    [
        CUT,
        f"WITH rates AS ({CUT}) SELECT * FROM rates",
        f"SELECT * FROM ({CUT}) AS rates WHERE rate IS NOT NULL",
        "SELECT provider, median(payment_attempts) AS rate FROM fact_payments_hourly GROUP BY ALL",
        "SELECT provider, quantile_cont(payment_attempts, 0.5) AS rate FROM fact_payments_hourly GROUP BY ALL",
        "SELECT provider, stddev_samp(payment_attempts) AS rate FROM fact_payments_hourly GROUP BY ALL",
        "SELECT provider, CASE WHEN payment_attempts > 0 THEN ROUND(ABS(1.0)) ELSE 0 END AS rate "
        "FROM fact_payments_hourly ORDER BY provider LIMIT 5",
        "SELECT provider, extract(hour from date_trunc('hour', ts)) AS rate FROM fact_payments_hourly",
        "SELECT a.provider, a.payment_attempts AS rate FROM fact_payments_hourly a "
        "JOIN fact_payments_hourly b USING (ts, country, platform, provider)",
        "SELECT '-- literal' AS provider, count(*) AS rate FROM log_events",
    ],
)
def test_valid_cuts_mint_rerunnable_receipts(runner: Runner, sql: str) -> None:
    assert validate(sql).accepted
    result = run_check(runner, sql, AS_OF, PREDICT, "comparison")
    assert result.accepted and result.receipt_id
    receipt = runner.receipts[result.receipt_id]
    assert receipt.as_of == AS_OF
    assert runner.rerun(receipt.id) == (receipt.result_hash, True)


def test_direction_is_judged_and_future_rows_are_absent(runner: Runner) -> None:
    lower = run_check(runner, CUT, AS_OF, PREDICT, "comparison")
    higher = run_check(runner, CUT, AS_OF, PREDICT | {"relation": "a_gt_b"}, "comparison")
    assert (lower.outcome, higher.outcome) == ("holds", "fails")
    assert lower.receipt_id and higher.receipt_id
    assert runner.receipts[lower.receipt_id].result_hash == runner.receipts[higher.receipt_id].result_hash
    future = run_check(
        runner,
        "SELECT provider, payment_attempts AS rate FROM fact_payments_hourly "
        "WHERE ts > TIMESTAMP '2026-11-20 02:00:00'",
        AS_OF,
        PREDICT,
        "future",
    )
    assert future.accepted and future.receipt_id and future.rows == [] and future.outcome is None


def test_bad_predictions_and_binding_errors_fall_back(runner: Runner) -> None:
    assert run_check(runner, CUT, AS_OF, {**PREDICT, "min_gap": float("nan")}, "bad").rule == "prediction"
    assert run_check(runner, "SELECT missing FROM log_events", AS_OF, PREDICT, "bad").rule == "execution"
    assert runner.query_count == 0


def test_capped_result_is_receipted_but_inconclusive(runner: Runner) -> None:
    result = run_check(runner, "SELECT country, orders AS rate FROM fact_orders_hourly", AS_OF, PREDICT, "cap")
    assert result.accepted and len(result.rows) == 200 and result.outcome is None and result.receipt_id
    assert "row limit" in result.summary
    assert runner.rerun(result.receipt_id)[1]
