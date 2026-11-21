from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.sources import ReplaySource
from argus.contracts.events import Event, EventType, InvestigationStepPayload
from argus.market import MarketAssessment
from bench.cli import main


def test_market_fixture_matches_wire_contract() -> None:
    event = Event.model_validate_json(Path(__file__).with_name("fixtures").joinpath("market-step.json").read_text())
    assert event.type is EventType.INVESTIGATION_STEP
    step = InvestigationStepPayload.model_validate(event.payload).step
    result = MarketAssessment.model_validate(step.data["market_control"])
    assert result.verdict == "market" and result.receipt_id in step.receipts
    assert result.hour == result.series[-1].ts


@pytest.mark.e2e
def test_s5_sealed_grade_and_evidence_over_sse(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work = tmp_path / "bench"
    recording = tmp_path / "recording"
    assert main(["record", "s5", "--seed", "7", "--work", str(work), "--out", str(recording)]) == 0
    result = capsys.readouterr().out
    assert "s5_market_dip" in result and "s5_checkout_routing_fault" in result
    assert result.count("grade 4") == 2 and "pages 1, false alarms 0, truth verified True" in result
    case = work / "s5-7"
    assert main(["verify", str(case)]) == 0
    assert {p.name for p in (case / "world").iterdir()} == {"world.duckdb", "manifest.json"}
    source = ReplaySource(recording, world=case / "world" / "world.duckdb")
    with TestClient(create_app(source, web_dist=tmp_path)) as client:
        finish = client.post("/replay", json={"action": "end"}).json()
        assert finish["finished"]
        response = client.get("/events", params={"limit": finish["total"]})
        assessments = []
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line.removeprefix("data: "))
            step = event.get("payload", {}).get("step", {})
            if step.get("tool") == "check_control_group":
                assessments.append(MarketAssessment.model_validate(step["data"]["market_control"]))

        assert {a.node for a in assessments if a.verdict == "market"} == {"sessions", "orders", "gmv"}
        session = next(a for a in assessments if a.node == "sessions")
        assert session.series[-1].ts == session.hour
        receipt = client.post(f"/receipts/{session.receipt_id}/rerun").json()
        assert receipt["matches"] and receipt["rows"] == len(session.series)
        assert any(n["kind"] == "expected" and n["node"] == "sessions" for n in client.get("/notes").json())
        (incident,) = client.get("/incidents").json()
        assert incident["verdict"] == "SUPPORTED_CAUSE"
        assert incident["root_node"] == "payment_success_rate"
        assert incident["segment"] == {"country": "DE", "platform": "android", "provider": "PayCo"}
