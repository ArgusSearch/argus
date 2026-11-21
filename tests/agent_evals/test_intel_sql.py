"""Exercise the SQL gate against local simulator data and the real receipt runner."""

from __future__ import annotations

from datetime import timedelta

import pytest
from test_intel_board import stage2
from test_runtime_gates import world_case as world_case

from argus.semantic.runner import Runner, sql_ts

PREDICT = {"value": "value", "group": "provider", "a": ["PayCo"], "b": "rest", "relation": "a_lt_b", "min_gap": 0.01}
HOSTILE = (
    "CREATE TABLE disallowed (id INT)",
    "DELETE FROM raw_payments_hourly",
    "SELECT 1; SELECT 2",
    "SELECT * FROM raw_payments_hourly",
    "SELECT * FROM main.fact_payments_hourly",
    'SELECT * FROM "fact_payments_hourly"',
    "WITH fact_payments_hourly AS (SELECT 1) SELECT * FROM fact_payments_hourly",
    "SELECT * FROM read_csv('absent.csv')",
    "SELECT * FROM read_parquet('absent.parquet')",
    "SELECT * FROM glob('absent')",
    "SELECT * FROM range(2)",
    "ATTACH ':memory:' AS other",
    "COPY (SELECT 1) TO 'absent.csv'",
    "PRAGMA version",
    "SET VARIABLE as_of = '2000-01-01'",
    "SELECT getvariable('as_of')",
    "INSTALL json",
    "LOAD json",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM duckdb_tables()",
    "SELECT * FROM truth_events",
    "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 2) SELECT * FROM n",
    "SELECT * FROM log_calendar CROSS JOIN log_deploys",
    "SELECT SUM(p.payment_attempts) FROM fact_payments_hourly p JOIN fact_funnel_hourly f USING (ts)",
    "SELECT /* comment */ * FROM log_events",
    "EXPLAIN SELECT * FROM log_events",
    "CALL checkpoint()",
    "SELECT '" + "a" * 2000 + "' AS oversize",
)

CUTS = (
    "SELECT provider, SUM(payment_attempts) AS value FROM fact_payments_hourly GROUP BY provider",
    "SELECT country, SUM(sessions) AS value FROM fact_funnel_hourly GROUP BY country",
    "SELECT platform, SUM(orders) AS value FROM fact_orders_hourly GROUP BY platform",
    "SELECT country, AVG(ad_spend) AS value FROM fact_ads_hourly GROUP BY country",
    "SELECT country, SUM(planned_spend) AS value FROM fact_ad_plan_hourly GROUP BY country",
    "SELECT kind, COUNT(*) AS value FROM log_deploys GROUP BY kind",
    "SELECT provider, COUNT(*) AS value FROM log_provider_status GROUP BY provider",
    "SELECT vertical, COUNT(*) AS value FROM dim_advertiser GROUP BY vertical",
    "WITH p AS (SELECT provider, SUM(payment_attempts) AS value FROM fact_payments_hourly "
    "GROUP BY provider) SELECT provider, value FROM p",
    "SELECT platform, MAX(value) AS value FROM (SELECT platform, checkouts AS value FROM fact_funnel_hourly) f "
    "GROUP BY platform",
)


@pytest.fixture(scope="module")
def payments(world_case):
    case = world_case("s1")
    (incident,) = stage2(case, first_incident=True).book.incidents.values()
    return case.world, incident.findings


@pytest.mark.parametrize("sql", HOSTILE)
def test_e19_rejects_before_querying(payments, sql, monkeypatch):
    from argus.evidence.sqlgate import run_check, validate

    world, findings = payments
    runner = Runner(world)

    def unexpected_execution(*args, **kwargs):
        pytest.fail("a disallowed statement reached the database")

    monkeypatch.setattr(runner, "query", unexpected_execution)
    try:
        before = runner.query_count
        requested = validate(sql)
        result = run_check(runner, sql, findings.as_of, PREDICT, "eval rejected SQL")
        assert not requested.accepted and requested.rule
        assert not result.accepted and result.rule == requested.rule
        assert not result.receipt_id and runner.query_count == before
    finally:
        runner.close()


@pytest.mark.parametrize("sql", CUTS)
def test_e19_accepts_with_reproducible_receipt(payments, sql):
    from argus.evidence.sqlgate import run_check

    world, findings = payments
    runner = Runner(world)
    try:
        result = run_check(runner, sql, findings.as_of, PREDICT, "eval legitimate cut")
        assert result.accepted and result.rows and result.receipt_id, result
        assert runner.rerun(result.receipt_id)[1]
    finally:
        runner.close()


def test_e19_future_hours_are_hidden(payments):
    from argus.evidence.sqlgate import run_check

    world, findings = payments
    runner = Runner(world)
    try:
        future = sql_ts(findings.as_of + timedelta(hours=1))
        sql = f"SELECT provider, payment_attempts AS value FROM fact_payments_hourly WHERE ts = {future}"
        assert runner.fetch(sql, findings.as_of + timedelta(hours=5))
        result = run_check(runner, sql, findings.as_of, PREDICT, "eval time cut")
        assert result.accepted and result.rows == [] and result.receipt_id
        assert runner.receipts[result.receipt_id].rows == 0
        assert runner.rerun(result.receipt_id)[1]
    finally:
        runner.close()


def comparison_sql(start, end):
    return (
        "SELECT provider, SUM(payment_successes) / NULLIF(SUM(payment_attempts), 0) AS value "
        "FROM fact_payments_hourly "
        f"WHERE country = 'DE' AND platform = 'android' AND ts BETWEEN {sql_ts(start)} AND {sql_ts(end)} "
        "GROUP BY provider ORDER BY provider"
    )


def test_e20_comparison_and_inversion_are_judged(payments):
    from argus.evidence.sqlgate import run_check

    world, findings = payments
    sql = comparison_sql(findings.window.start, findings.window.end)
    hashes = []
    for _ in range(2):
        runner = Runner(world)
        try:
            for relation, outcome in (("a_lt_b", "holds"), ("a_gt_b", "fails")):
                result = run_check(runner, sql, findings.as_of, PREDICT | {"relation": relation}, "eval PayCo cut")
                assert result.accepted and result.outcome == outcome and result.receipt_id, result
                receipt_hash, matches = runner.rerun(result.receipt_id)
                assert matches
                hashes.append(receipt_hash)
        finally:
            runner.close()
    assert len(set(hashes)) == 1
