"""Where the extension lanes meet: demo playback, the narrator's morning report, counterfactual replay and S5.

Each lane tests itself; these tests check the seams between them through the one API Mission Control uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.recording import FIXTURES
from argus.api.sources import ReplaySource
from argus.contracts.events import Event, EventType, InvestigationStepPayload
from argus.contracts.findings import Incident, Note, Verdict
from argus.counterfactual.models import CounterfactualResult
from argus.demo.contracts import DemoBeat, MorningReport, VerdictBeat
from argus.demo.timeline import load_timeline
from argus.narrator.morning import MorningReport as NarratorReport
from argus.runtime.loop import Runtime
from mockmart.sim import WorldConfig
from mockmart.world import generate

RECORDINGS = {"quiet": FIXTURES / "quiet", "s1": FIXTURES, "s2": FIXTURES / "s2", "s3": FIXTURES / "s3"}
RECORDINGS |= {"s4": FIXTURES / "s4", "s5": FIXTURES / "s5"}


def _frames(body: str) -> list[dict[str, str]]:
    blocks = [block for block in body.split("\n\n") if block.startswith(("event:", "id:"))]
    return [dict(line.split(": ", 1) for line in block.splitlines() if ": " in line) for block in blocks]


def _replay(scenario: str, web_dist: Path) -> TestClient:
    return TestClient(create_app(ReplaySource(RECORDINGS[scenario], seconds_per_tick=0), web_dist=web_dist))


def _play(client: TestClient, scenario: str) -> dict[str, DemoBeat]:
    """Play a whole demo run at full speed over SSE; the first beat of each kind, as the wire delivered it."""
    run = client.post("/demo/start", json={"scenario": scenario, "speed": 100}).raise_for_status().json()
    frames = _frames(client.get("/demo/events", params={"run_id": run["run_id"]}).text)
    assert frames[-1]["event"] == "complete"
    beats: dict[str, DemoBeat] = {}
    for frame in frames[:-1]:
        beat = DemoBeat.model_validate_json(frame["data"])
        beats.setdefault(beat.kind, beat)
    return beats


def _skip_to(client: TestClient, kind: str) -> None:
    """Pause the current demo run and skip until its first `kind` beat is due."""
    state = client.post("/demo/control", json={"action": "pause"}).raise_for_status().json()
    cues = load_timeline(state["scenario"]).cues
    while cues[state["beat_index"]].kind != kind:
        state = client.post("/demo/control", json={"action": "skip"}).raise_for_status().json()


def test_demo_morning_beat_links_the_narrator_report_of_its_own_recording(tmp_path: Path) -> None:
    # The server replays S1; the demo plays S4. Every link the demo hands out must stay on S4.
    with _replay("s1", tmp_path) as client:
        client.post("/replay", json={"action": "end"}).raise_for_status()
        beats = _play(client, "s4")
        verdict, morning = beats["verdict"].data, beats["morning_report"].data
        assert isinstance(verdict, VerdictBeat) and isinstance(morning, MorningReport)
        assert morning.report == "/demo/report/morning"

        # The report is part of the morning beat: a fresh run reveals it only when that beat is due.
        client.post("/demo/start", json={"scenario": "s4"}).raise_for_status()
        assert client.get(morning.report).status_code == 404
        _skip_to(client, "verdict")
        assert client.get(morning.report).status_code == 404
        _skip_to(client, "morning_report")

        report = NarratorReport.model_validate(client.get(morning.report).raise_for_status().json())
        assert report.stream == "demo-s4"
        assert report.activity.until == morning.digest.until
        lines = {line.id: line for line in report.lines}
        incident = verdict.incident
        assert incident.verdict.value in lines[f"{incident.id}:verdict"].text
        assert "ad-pacer" in lines[f"{incident.id}:verdict"].text
        assert "Roll back" in lines[f"{incident.id}:approval"].text
        (run,) = report.investigations
        assert (run.playbook_id, run.incident_id, run.finished) == ("ads_spike", incident.id, True)
        # The server's own report is still the S1 run it replays.
        assert "PayCo" in client.get("/report/morning").json()["markdown"]

        markdown = client.get(morning.report, params={"format": "markdown"})
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert markdown.text == report.markdown
        assert "](/receipts/" not in markdown.text and "](/report/" not in markdown.text

        links = {link.href: link for line in report.lines for link in line.receipts}
        links[report.activity_receipt.href] = report.activity_receipt
        assert all(href.startswith("/demo/") for href in links)
        for link in links.values():
            evidence = client.get(link.href)
            assert evidence.status_code == 200, link.href
            assert evidence.json()["id"] == link.id
            if link.source == "semantic":
                assert client.post(link.rerun_href).status_code == 409
            else:
                assert client.get(link.rerun_href).json() == evidence.json()
        activity = client.get(report.activity_receipt.href).json()
        assert activity["rows"] == [report.activity.model_dump(mode="json")]
        stale = report.activity_receipt.href.replace("stream=demo-s4", "stream=demo-s1")
        assert client.get(stale).status_code == 404

        # A replaced run no longer serves its links.
        old_run = client.get("/demo/state").json()["run_id"]
        client.post("/demo/control", json={"action": "restart"}).raise_for_status()
        assert client.get(morning.report, params={"run_id": old_run}).status_code == 409


@pytest.mark.e2e
def test_demo_verdict_beat_links_the_same_counterfactual_the_incident_route_serves(tmp_path: Path) -> None:
    with _replay("s4", tmp_path) as client:
        client.post("/replay", json={"action": "end"}).raise_for_status()
        verdict = _play(client, "s4")["verdict"].data
        assert isinstance(verdict, VerdictBeat)
        assert verdict.counterfactual == "/demo/counterfactual"

        client.post("/demo/start", json={"scenario": "s4"}).raise_for_status()
        _skip_to(client, "evidence")
        assert client.get(verdict.counterfactual).status_code == 404
        _skip_to(client, "verdict")
        response = client.get(verdict.counterfactual)
        assert response.status_code == 200, response.text
        demo = CounterfactualResult.model_validate(response.json())
        root = verdict.incident.findings.root
        assert root and root.evidence
        assert demo.receipt.plan.intervention == root.evidence
        assert demo.explained_share > 0.9

        # The server replays the same recording, so its incident route proves the same replay.
        served = client.get(f"/incidents/{verdict.incident.id}/counterfactual")
        assert served.status_code == 200, served.text
        assert CounterfactualResult.model_validate(served.json()) == demo


def test_s5_market_control_reaches_the_stream_notes_and_morning_report(tmp_path: Path) -> None:
    with _replay("s5", tmp_path) as client:
        client.post("/replay", json={"action": "end"}).raise_for_status()
        recorded = (RECORDINGS["s5"] / "events.jsonl").read_text().splitlines()
        frames = _frames(client.get("/events", params={"limit": len(recorded)}).text)
        events = [Event.model_validate_json(frame["data"]) for frame in frames if frame["event"] != "stream"]
        market = [
            InvestigationStepPayload.model_validate(event.payload)
            for event in events
            if event.type is EventType.INVESTIGATION_STEP and event.payload["step"]["tool"] == "check_control_group"
        ]
        verdicts = {step.step.data["market_control"]["node"]: step.step.data["market_control"] for step in market}
        assert {node: check["verdict"] for node, check in verdicts.items()} == {
            "sessions": "market",
            "orders": "market",
            "gmv": "market",
        }

        notes = [Note.model_validate(note) for note in client.get("/notes").json()]
        assert sorted(note.node for note in notes) == ["gmv", "orders", "sessions"]
        assert all(note.kind == "expected" for note in notes)
        (incident,) = [Incident.model_validate(item) for item in client.get("/incidents").json()]
        assert incident.verdict is Verdict.SUPPORTED_CAUSE and incident.root_node == "payment_success_rate"
        root = incident.findings.root
        assert root and root.evidence and root.evidence.ref == "dep_checkout-routing_retry-policy"

        report = NarratorReport.model_validate(client.get("/report/morning").json())
        assert (report.activity.expected_notes, report.activity.incidents, report.activity.anomalies) == (3, 1, 4)
        lines = {line.id: line for line in report.lines}
        for note in notes:
            line = lines[f"note:{note.id}"]
            assert line.section == "decided" and "market-wide decline" in line.text
            # The note cites the control-group receipt the market check ran.
            assert verdicts[note.node]["receipt_id"] in {link.id for link in line.receipts}
        assert "checkout" in lines[f"{incident.id}:verdict"].text.lower()
        # The cause is our own routing change, so Argus asks to undo it, not to route around PayCo.
        assert "Roll back dep_checkout-routing_retry-policy" in lines[f"{incident.id}:approval"].text
        # Its own deploy also answers whether the fault sits inside PayCo, so the report does not ask that.
        uncertainty = lines.get(f"{incident.id}:uncertainty")
        assert uncertainty is None or "inside PayCo" not in uncertainty.text
        playbooks = sorted((run.playbook_id, run.incident_id or "") for run in report.investigations)
        assert playbooks == [
            ("revenue_drop", ""),
            ("revenue_drop", ""),
            ("revenue_drop", incident.id),
            ("traffic_drop", ""),
        ]
        assert client.get("/autonomy").status_code == 200

        # S5's cause is no MockMart intervention the counterfactual replay can switch off.
        counterfactual = client.get(f"/incidents/{incident.id}/counterfactual")
        assert counterfactual.status_code == 409 and counterfactual.json()["detail"]


@pytest.mark.e2e
def test_s5_runtime_recommends_rolling_back_its_supported_deploy(tmp_path: Path) -> None:
    world = generate("s5", WorldConfig(seed=1), tmp_path / "world").world
    runtime = Runtime(world)
    runtime.run()
    (incident,) = runtime.book.incidents.values()
    root = incident.findings.root
    assert root and root.evidence and root.evidence.log == "log_deploys" and "provider" in root.segment
    action = incident.findings.suggested_action
    assert action and action.needs_approval
    assert action.text.startswith(f"Roll back {root.evidence.ref} for ")
    assert not any("inside PayCo" in question for question in incident.findings.uncertain)


@pytest.mark.parametrize("scenario", sorted(RECORDINGS))
def test_every_recording_serves_the_extension_routes(scenario: str, tmp_path: Path) -> None:
    with _replay(scenario, tmp_path) as client:
        client.post("/replay", json={"action": "end"}).raise_for_status()
        report = NarratorReport.model_validate(client.get("/report/morning").raise_for_status().json())
        assert report.activity.ticks == 120
        assert client.get("/autonomy").raise_for_status().json()["playbooks"]
        incidents = client.get("/incidents").json()
        assert len(incidents) == (1 if scenario in {"s1", "s4", "s5"} else 0)
        assert client.get("/incidents/INC-0404/counterfactual").status_code == 404
        paths = json.loads(client.get("/openapi.json").text)["paths"]
        for path in (
            "/report/morning",
            "/report/morning/queries/{query_id}",
            "/autonomy",
            "/incidents/{incident_id}/counterfactual",
            "/demo/start",
            "/demo/events",
            "/demo/counterfactual",
            "/demo/report/morning",
            "/demo/report/morning/queries/{query_id}",
        ):
            assert path in paths, path
