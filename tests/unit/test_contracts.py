"""The six contracts: generated artifacts are current, examples and fixtures validate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argus.contracts import events, findings, graph, metric
from argus.contracts.export import OUT, artifacts
from argus.contracts.metric import MetricSqlError, load_metric, parse_metric
from argus.contracts.world import ALL_TABLES, DIMENSIONS, render_schema_sql

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"


def test_generated_contract_artifacts_are_current() -> None:
    for name, content in artifacts().items():
        assert (OUT / name).read_text() == content, f"contracts/{name} is stale: run `make contracts`"


def test_schema_sql_creates_every_view(tmp_path: Path) -> None:
    import duckdb

    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute(render_schema_sql())
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert {t.name for t in ALL_TABLES} | {"log_events"} <= names


def test_metric_examples_parse() -> None:
    files = sorted((REPO / "metrics").glob("*.yml"))
    assert files, "metrics/ must hold at least one example"
    for path in files:
        parsed = parse_metric(load_metric(path))
        assert parsed.tables and all(d in DIMENSIONS for d in parsed.dims)


def test_metric_ratio_is_detected() -> None:
    m = metric.MetricDefinition(
        name="roas_x",
        description="d",
        sql="SELECT ts, advertiser_id, SUM(attributed_gmv) / NULLIF(SUM(ad_spend), 0) AS value "
        "FROM fact_ads_hourly GROUP BY ALL",
    )
    parsed = parse_metric(m)
    assert parsed.numerator_sql == "SUM(attributed_gmv)" and parsed.dims == ["advertiser_id"]


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("SELECT ts, SUM(orders) AS value FROM raw_orders_hourly GROUP BY ALL", "unknown or non-fact"),
        ("SELECT ts, SUM(orders) AS total FROM fact_orders_hourly GROUP BY ALL", "aliased AS value"),
        ("SELECT country, SUM(orders) AS value FROM fact_orders_hourly GROUP BY ALL", "include ts"),
        ("SELECT ts, AVG(orders) AS value FROM fact_orders_hourly GROUP BY ALL", "not allowed"),
        (
            "SELECT ts, SUM(orders) AS value FROM fact_orders_hourly JOIN fact_funnel_hourly ON TRUE GROUP BY ALL",
            "USING",
        ),
        ("SELECT ts, SUM(orders) AS value FROM fact_orders_hourly", "GROUP BY"),
    ],
)
def test_metric_sql_outside_the_allowed_form_is_rejected(sql: str, reason: str) -> None:
    with pytest.raises(MetricSqlError, match=reason):
        parse_metric(metric.MetricDefinition(name="bad", description="d", sql=sql))


def test_metric_yaml_rejects_extra_keys() -> None:
    with pytest.raises(ValueError):
        metric.MetricDefinition.model_validate({"name": "x", "description": "d", "sql": "s", "parent": "gmv"})


def test_fixtures_validate_against_the_contracts() -> None:
    graph.Graph.model_validate_json((FIXTURES / "graph.json").read_text())
    findings.Findings.model_validate_json((FIXTURES / "findings.json").read_text())
    for inc in json.loads((FIXTURES / "incidents.json").read_text()):
        findings.Incident.model_validate(inc)
    for note in json.loads((FIXTURES / "notes.json").read_text()):
        findings.Note.model_validate(note)
    for receipt in json.loads((FIXTURES / "receipts.json").read_text()):
        findings.Receipt.model_validate(receipt)
    seen = set()
    for line in (FIXTURES / "events.jsonl").read_text().splitlines():
        ev = events.Event.model_validate_json(line)
        seen.add(ev.type)
    assert {events.EventType.TICK, events.EventType.ANOMALY_OPENED, events.EventType.INVESTIGATION_STEP} <= seen
    assert {events.EventType.INCIDENT_UPDATED, events.EventType.EDGE_STATUS} <= seen


def test_event_payload_must_match_its_type() -> None:
    with pytest.raises(ValueError):
        events.Event(seq=1, type=events.EventType.TICK, sim_ts="2026-11-20T00:00:00", payload={"nope": 1})
