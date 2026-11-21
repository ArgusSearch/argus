"""Release invariants on genuine provider output and the matching app recordings."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts.agent_eval.bundle import Bundle, ReceiptProof, read_bundle
from scripts.agent_eval.qualify import check_adaptive

from argus.agent.types import ActivityRecord, ProposalView
from argus.contracts.findings import Incident, IncidentState, Verdict
from argus.narrator.report import unbacked_numbers
from argus.semantic.runner import Runner
from mockmart.sim import WorldConfig
from mockmart.world import generate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "agent" / "v1"


@pytest.fixture(scope="module", params=("s1", "s4"))
def capture(request: pytest.FixtureRequest) -> Bundle:
    return require_capture(request.param)


def require_capture(scenario: str) -> Bundle:
    index = FIXTURES / "accepted.json"
    assert index.is_file(), "S1 and S4 live recordings still need independent pins in fixtures/agent/v1/accepted.json"
    pins = json.loads(index.read_bytes())
    assert set(pins) == {"s1", "s4"}, "acceptance needs a pin for each scenario"
    bundle = read_bundle(FIXTURES / scenario, expected_digest=pins[scenario])
    assert bundle.manifest.scenario == scenario and bundle.manifest.seed == 1
    return bundle


def only_incident(bundle: Bundle, path: str = "incidents.json") -> Incident:
    incidents = bundle.documents.get(path, [])
    assert len(incidents) == 1, f"expected one incident in {bundle.manifest.scenario}/{path}"
    return Incident.model_validate(incidents[0])


def activity(bundle: Bundle) -> list[ActivityRecord]:
    return [ActivityRecord.model_validate(record) for record in bundle.documents["activity.jsonl"]]


def test_e01_recorded_scenarios_produce_one_supported_case(capture: Bundle) -> None:
    incident = only_incident(capture)
    assert incident.verdict == Verdict.SUPPORTED_CAUSE
    assert incident.findings.cost.llm_calls >= 2
    records = activity(capture)
    assert not [record for record in records if record.kind in {"fallback", "budget"}]
    run_ids = {record.run_id for record in records if record.incident_id == incident.id and record.run_id is not None}
    assert check_adaptive(capture, run_ids), "no second model-selected call after a receipted observation"


def test_e02_recorded_root_and_scope(capture: Bundle) -> None:
    incident = only_incident(capture)
    s1 = capture.manifest.scenario == "s1"
    assert incident.root_node == ("payment_success_rate" if s1 else "pacing_ratio")
    root = incident.findings.root
    assert root is not None and root.evidence is not None
    if s1:
        assert root.segment["country"] == "DE" and root.segment["platform"] == "android"
        assert "payco" in root.evidence.description.casefold() or "payco" in root.evidence.ref.casefold()
    else:
        assert root.evidence.ref == "dep_ad-pacer_1.7.0"
        proposed = [ProposalView.model_validate(action) for action in capture.documents["actions.json"]]
        assert len(proposed) == 1 and proposed[0].scope == {"country": ["DE", "FR"]}


def test_e03_s1_android_release_is_refuted_with_a_real_holdout() -> None:
    capture = require_capture("s1")
    incident = only_incident(capture)
    alternatives = [
        item for item in incident.findings.ruled_out if item.evidence and item.evidence.ref == "dep_android-app_8.3.0"
    ]
    assert len(alternatives) == 1 and alternatives[0].result == "refuted" and alternatives[0].receipts
    holdouts = [
        record.observation
        for record in activity(capture)
        if record.observation is not None and record.tool == "holdout_check"
    ]
    assert any(
        item.ledger is not None
        and item.ledger.status == "refuted"
        and set(alternatives[0].receipts) & {link.receipt_id for link in item.receipt_refs}
        for item in holdouts
    )


def test_e04_factual_receipts_rerun_at_their_recorded_clock(capture: Bundle, tmp_path: Path) -> None:
    manifest = capture.manifest
    world_start = datetime.fromisoformat(manifest.world["world_start"])
    world_end = datetime.fromisoformat(manifest.world["world_end"])
    live_start = datetime.fromisoformat(manifest.world["live_start"])
    cfg = WorldConfig(
        seed=manifest.seed,
        start=world_start,
        days=(world_end - world_start).days,
        live_days=(world_end - live_start).days,
        base_sessions=manifest.world.get("base_sessions", WorldConfig.base_sessions),
    )
    runner = Runner(generate(manifest.scenario, cfg, tmp_path / "world").world)
    verified: set[tuple[str, datetime, str]] = set()
    try:
        for key, value in capture.documents["receipts.json"].items():
            proof = ReceiptProof.model_validate(value)
            receipt = proof.receipt
            binding = (receipt.sql, receipt.as_of, receipt.result_hash)
            if binding in verified:
                continue
            runner.receipts[key] = receipt
            result_hash, match = runner.rerun(key)
            assert match, f"{manifest.scenario}/{key} returned {result_hash}, expected {receipt.result_hash}"
            verified.add(binding)
        assert verified, f"no factual receipt reruns in {manifest.scenario}"
    finally:
        runner.close()


def test_e04_published_narrative_uses_bound_numbers(capture: Bundle) -> None:
    findings = only_incident(capture).findings
    facts: dict[str, Any] = {}
    for record in activity(capture):
        if record.observation is not None:
            facts.update({fact.id: fact.value for fact in record.observation.fact_handles if fact.receipts})
        if record.kind in {"report", "chat_answer"}:
            assert not unbacked_numbers(record.text, findings, facts), f"unsupported number at activity {record.seq}"
    for answer in capture.documents["ask.jsonl"]:
        response = answer["response"]
        assertions = {
            claim["claim_id"]: claim["value"]
            for claim in response["claims"]
            if claim.get("value") is not None and claim["receipts"]
        }
        assert not unbacked_numbers(response["answer"], findings, assertions)


def test_e05_prediction_is_journaled_before_the_observation(capture: Bundle) -> None:
    records = activity(capture)
    judged = [record for record in records if record.observation is not None and record.observation.ledger is not None]
    assert judged, f"{capture.manifest.scenario}: no judged model observations"
    calls: dict[tuple[str | None, str | None], ActivityRecord] = {}
    for record in records:
        key = (record.run_id, record.tool)
        if record.kind == "tool_call":
            calls[key] = record
        if record.kind != "tool_result" or record.observation is None or record.observation.ledger is None:
            continue
        prediction = record.observation.ledger.hypothesis.prediction
        call = calls.get(key)
        assert call and call.seq < record.seq, f"missing call before result {record.seq}"
        assert prediction and (prediction in call.text or prediction in json.dumps(call.args, ensure_ascii=False)), (
            f"prediction missing before result {record.seq}"
        )


def test_e10_recorded_rollout_finishes_with_verified_twin_and_resolved_incident() -> None:
    capture = require_capture("s4")
    incident = only_incident(capture, "approve/incidents.json")
    proposal = ProposalView.model_validate(capture.documents["approve/actions.json"][0])
    assert proposal.state == "VERIFIED" and proposal.effect is not None
    assert proposal.effect.state == "VERIFIED" and proposal.success_rule.comparator == "untreated_twin"
    assert proposal.success_rule.hours >= 3
    lag = int(capture.manifest.world["delivery_lag_hours"])
    assert proposal.effect.checked_at >= proposal.effective_at + timedelta(hours=lag + 2)
    assert len({link.world_revision for link in proposal.effect.receipt_refs}) >= 2
    assert incident.state is IncidentState.RESOLVED and incident.resolved_at is not None
    assert incident.resolved_at >= proposal.effective_at
