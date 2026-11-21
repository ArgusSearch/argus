"""Grade replay against the sealed scenarios only after the endpoint returns."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from math import ceil
from pathlib import Path
from statistics import mean

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.sources import FIXTURES, ReplaySource
from argus.contracts.findings import Incident, Verdict
from argus.counterfactual import ReplayUnavailable, counterfactual
from argus.counterfactual.models import CounterfactualResult, WorldConfig
from argus.counterfactual.replay import make_plan
from argus.semantic.runner import Runner, sql_ts
from mockmart.sim import WorldConfig as MockMartConfig
from mockmart.truth import read_truth
from mockmart.world import WorldPaths, generate

HOUR = timedelta(hours=1)
GAP_TOLERANCE = 0.10
S4_RECEIPT = Path(__file__).parent / "fixtures" / "s4_receipt.json"
ROUTE = "/incidents/INC-0001/counterfactual"


def _read_replay(fixture_dir: Path, web_dist: Path) -> CounterfactualResult:
    source = ReplaySource(fixture_dir, seconds_per_tick=0)
    with TestClient(create_app(source, web_dist=web_dist)) as client:
        assert client.post("/replay", json={"action": "end"}).json()["finished"]
        assert client.get("/incidents/missing/counterfactual").status_code == 404
        response = client.get(ROUTE)
        assert response.status_code == 200, response.text
        return CounterfactualResult.model_validate(response.json())


def _assert_restoration(result: CounterfactualResult, truth_share: float) -> None:
    assert result.explained_share == pytest.approx(truth_share, abs=GAP_TOLERANCE)
    assert result.gap.removed == pytest.approx(result.gap.factual - result.gap.counterfactual)
    assert result.gap.removed / result.gap.factual == pytest.approx(result.explained_share)


@pytest.mark.e2e
def test_s1_replay_restores_the_seeded_payco_probability(s1_world: WorldPaths, tmp_path: Path) -> None:
    result = _read_replay(FIXTURES, tmp_path)
    truth = next(event for event in read_truth(s1_world.truth) if event["kind"] == "fault")
    plan = result.receipt.plan
    assert (plan.onset, plan.metric, plan.segment) == (truth["start_ts"], truth["root_node"], truth["segment"])
    assert plan.intervention.ref == truth["expected"]["evidence"]
    assert plan.intervention.ref not in truth["expected"]["ruled_out"]

    post_onset = [p for p in result.factual_series if p.hour >= truth["start_ts"]]
    fault = truth["magnitude"]["success_rate_fault"]
    normal = truth["magnitude"]["success_rate_normal"]
    truth_gap = sum(abs((fault if p.hour < truth["end_ts"] else normal) - p.expected) for p in post_onset)
    truth_remainder = sum(abs(normal - p.expected) for p in post_onset)
    _assert_restoration(result, 1 - truth_remainder / truth_gap)
    assert result.gap.factual == pytest.approx(truth_gap, rel=0.1)
    assert all(p.value == pytest.approx(normal, abs=0.04) for p in result.counterfactual_series)
    observed_fault = [p.value for p in post_onset if p.hour < truth["end_ts"]]
    assert mean(observed_fault) == pytest.approx(fault, abs=0.025)
    assert result.factual_series[:6] == result.counterfactual_series[:6]


@pytest.mark.e2e
def test_s4_replay_recovers_the_afternoon_delivery_hidden_by_daily_totals(tmp_path: Path) -> None:
    result = _read_replay(FIXTURES / "s4", tmp_path)
    paths = generate("s4", MockMartConfig(seed=1), tmp_path / "s4")
    truth = next(event for event in read_truth(paths.truth) if event["kind"] == "fault")
    plan = result.receipt.plan
    assert (plan.onset, plan.metric) == (truth["start_ts"], truth["root_node"])
    assert plan.intervention.ref in truth["expected"]["evidence_any"]
    assert len(result.factual_series) == 30

    runner = Runner(paths.world)
    try:
        rows = runner.fetch(
            f"""
            SELECT country, SUM(planned_spend)::DOUBLE AS plan
            FROM fact_ad_plan_hourly WHERE CAST(ts AS DATE) = CAST({sql_ts(truth["start_ts"])} AS DATE)
            GROUP BY country
            """,
            plan.as_of,
        )
    finally:
        runner.close()
    hit = {segment["country"] for segment in truth["expected"]["segments_any"]}
    holdout_share = sum(row["plan"] for row in rows if row["country"] not in hit) / sum(row["plan"] for row in rows)
    exhausted = truth["start_ts"] + ceil(truth["magnitude"]["burn_hour"] + 1.5) * HOUR
    for observed, replay in zip(result.factual_series, result.counterfactual_series, strict=True):
        assert observed.hour == replay.hour
        if observed.hour < truth["start_ts"]:
            assert observed.value == pytest.approx(1, abs=0.1)
        if observed.hour >= exhausted:
            assert observed.value == pytest.approx(holdout_share, abs=0.06)
            assert replay.value == pytest.approx(1, abs=0.1)
    # With only the rollout removed, the simulator's expected delivery follows the entire plan.
    _assert_restoration(result, 1.0)
    assert result.gap.factual > 10


def test_replay_stops_at_the_last_complete_hour_and_declines_expected_changes() -> None:
    incident = Incident.model_validate(json.loads((FIXTURES / "s4" / "incidents.json").read_text())[0])
    plan = make_plan(incident, WorldConfig(seed=1), incident.findings.as_of)
    assert plan.window.end == incident.findings.as_of - 2 * HOUR == plan.onset
    with pytest.raises(ReplayUnavailable, match="supported fault"):
        counterfactual(
            incident.model_copy(update={"findings": incident.findings.model_copy(update={"verdict": Verdict.EXPECTED})})
        )


@pytest.mark.e2e
def test_saved_receipt_is_verifiable_through_the_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "argus.cli", "counterfactual", "--receipt", str(S4_RECEIPT)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    replay = CounterfactualResult.model_validate_json(result.stdout)
    assert replay.receipt.model_dump(mode="json") == json.loads(S4_RECEIPT.read_text())
