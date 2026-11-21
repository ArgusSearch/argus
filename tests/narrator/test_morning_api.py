from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.recording import FIXTURES, Recording, load_recording
from argus.api.sources import LiveSource, ReplaySource
from argus.contracts.events import EventType
from argus.contracts.findings import Verdict
from argus.contracts.graph import EdgeStatus
from argus.narrator.autonomy import Autonomy
from argus.narrator.morning import MorningReport
from argus.narrator.playbooks import map_playbook
from mockmart.world import WorldPaths

STORIES = json.loads(Path(__file__).with_name("report_expectations.json").read_text())


@pytest.mark.parametrize("scenario", STORIES)
def test_recording_report_has_rerunnable_evidence(scenario: str, tmp_path: Path) -> None:
    fixtures = FIXTURES if scenario == "s1" else FIXTURES / scenario
    recording = load_recording(fixtures)
    source = ReplaySource(recording=recording, seconds_per_tick=0)
    with TestClient(create_app(source, web_dist=tmp_path)) as client:
        response = client.get("/report/morning")
        assert response.status_code == 200
        report = MorningReport.model_validate(response.json())
        expected = STORIES[scenario]
        assert report.activity.ticks == 120
        for key, count in expected["activity"].items():
            assert getattr(report.activity, key) == count
        lines = {line.id: line for line in report.lines}
        assert len(lines) == len(report.lines)
        for key, phrases in expected["lines"].items():
            assert all(phrase in lines[key].text for phrase in phrases)

        markdown = client.get("/report/morning?format=markdown")
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert markdown.text == report.markdown
        bullets = [line for line in markdown.text.splitlines() if line.startswith("- ")]
        assert len(bullets) == len(lines)
        assert all("](/" in line for line in bullets)

        activity_receipt = client.get(report.activity_receipt.href).json()
        assert activity_receipt["rows"] == [report.activity.model_dump(mode="json")]
        event_by_seq = {event.seq: event for event in recording.events}
        for ref in {ref.href: ref for line in report.lines for ref in line.receipts}.values():
            evidence = client.get(ref.href)
            assert evidence.status_code == 200, ref.href
            data = evidence.json()
            assert data["id"] == ref.id and data["sql"] and data["result_hash"].startswith("sha256:")
            if ref.source == "run":
                assert ref.rerun_method == "GET"
                assert client.get(ref.rerun_href).json() == data
                if ref.id.startswith("event-"):
                    event = event_by_seq[data["parameters"]["seq"]]
                    assert data["rows"] == [event.model_dump(mode="json")]
                if ref.id.startswith("findings-"):
                    seq = data["parameters"]["seq"]
                    snapshot = next(s.incident.findings for s in recording.incidents if s.seq == seq)
                    assert data["rows"] == [{"seq": seq, "findings": snapshot.model_dump(mode="json")}]
                    early = ref.href.replace(f"through_seq={report.through_seq}", f"through_seq={seq - 1}")
                    assert client.get(early).status_code == 404
            else:
                assert ref.rerun_method == "POST"
                assert ref.rerun_href == f"{ref.href}/rerun"

        if scenario == "s3":
            evidence = lines["note:note_0001"].receipts
            assert [ref.source for ref in evidence] == ["run", "run"]
            tick = client.get(evidence[1].href).json()["rows"][0]
            orders = next(f for f in tick["payload"]["freshness"] if f["table"] == "fact_orders_hourly")
            assert orders["status"] == "pending" and orders["completeness"] == 0.55

        book = expected["playbook"]
        registry = Autonomy.model_validate(client.get("/autonomy").json())
        if book:
            (run,) = report.investigations
            assert run.playbook_id == book and run.finished
            definition = next(item for item in registry.playbooks if item.id == book)
            assert [step.step_id for step in run.steps] == [step.id for step in definition.steps]
            trail = [
                event.payload["step"]["step"]
                for event in recording.events
                if event.type is EventType.INVESTIGATION_STEP
            ]
            assert sorted(index for step in run.steps for index in step.trail_steps) == trail
            assert next(step for step in run.steps if step.step_id == "verdict").status == "done"
        else:
            assert report.investigations == []
        assert any(line.section == "asks" for line in lines.values()) == (scenario in {"s1", "s4"})
        if scenario in {"s1", "s4"}:
            approval = lines["INC-0001:approval"]
            proof = client.get(approval.receipts[0].href).json()["rows"][0]["findings"]["suggested_action"]
            assert proof["needs_approval"] and proof["text"] in approval.text


def test_report_follows_replay_prefix_and_pins_query_results(tmp_path: Path) -> None:
    recording = load_recording(FIXTURES)
    source = ReplaySource(recording=recording)
    with TestClient(create_app(source, start=False, web_dist=tmp_path)) as client:
        empty = MorningReport.model_validate(client.get("/report/morning").json())
        assert empty.through_seq == 0 and empty.activity.ticks == 0 and empty.activity.since is None

        preview = next(event for event in recording.events if event.type is EventType.INVESTIGATION_STEP)
        for event in recording.events:
            source.bus.publish(event)
            if event.seq == preview.seq:
                break
        early = MorningReport.model_validate(client.get("/report/morning").json())
        proof = client.get(early.activity_receipt.href).json()
        assert early.activity.anomalies == 1 and early.activity.incidents == 0
        assert early.activity.investigations == 0 and all(line.incident_id is None for line in early.lines)
        assert not early.investigations[0].finished
        assert {step.status for step in early.investigations[0].steps} == {"done", "pending"}

        for event in recording.events:
            if event.seq > preview.seq:
                source.bus.publish(event)
        late = MorningReport.model_validate(client.get("/report/morning").json())
        assert late.activity.incidents == 1
        assert client.get(early.activity_receipt.href).json() == proof
        assert client.get(empty.activity_receipt.href).status_code == 200
        assert (
            client.get(early.activity_receipt.href.replace("/activity?", f"/event-{late.through_seq}?")).status_code
            == 404
        )
        assert client.get(early.activity_receipt.href.replace("/activity?", "/other-query?")).status_code == 404
        source.bus.reset()
        assert client.get(early.activity_receipt.href).status_code == 404
        reset = MorningReport.model_validate(client.get("/report/morning").json())
        assert reset.stream != early.stream and reset.activity.ticks == 0 and reset.investigations == []


def test_ambiguous_cause_and_graph_probation_require_review(tmp_path: Path) -> None:
    recording = load_recording(FIXTURES)
    update = next(event for event in recording.events if event.type is EventType.INCIDENT_UPDATED)
    update = update.model_copy(
        update={"payload": {**update.payload, "verdict": Verdict.HYPOTHESIS, "title": "Investigate the cause"}}
    )
    node = recording.graph.nodes[0].model_copy(update={"state": "probation"})
    edge = recording.graph.edges[0].model_copy(update={"status": EdgeStatus.PROBATION})
    graph = recording.graph.model_copy(
        update={"nodes": [node, *recording.graph.nodes[1:]], "edges": [edge, *recording.graph.edges[1:]]}
    )
    source = ReplaySource(recording=Recording([update], graph), seconds_per_tick=0)
    with TestClient(create_app(source, web_dist=tmp_path)) as client:
        autonomy = Autonomy.model_validate(client.get("/autonomy").json())
        assert {"review_probation", "review_ambiguous_cause", "approve_action"} == {r.id for r in autonomy.asks_first}
        assert {("node", node.id), ("edge", edge.id)} <= {(case.kind, case.id) for case in autonomy.probation}
        assert {rule.id for rule in autonomy.decides_alone}.isdisjoint(rule.id for rule in autonomy.asks_first)
        assert {book.id for book in autonomy.playbooks} == {
            "ads_drop",
            "ads_spike",
            "revenue_drop",
            "revenue_spike",
            "traffic_drop",
            "traffic_spike",
        }
        report = MorningReport.model_validate(client.get("/report/morning").json())
        (review,) = [line for line in report.lines if line.section == "asks"]
        assert review.id == "INC-0001:review" and "Further evidence" in review.text
        assert client.get(review.receipts[0].href).json()["rows"][0]["payload"]["verdict"] == "HYPOTHESIS"


def test_untagged_findings_map_to_the_same_playbook() -> None:
    recording = load_recording(FIXTURES)
    incident = recording.incidents[-1].incident
    findings = incident.findings
    trail = [step.model_copy(update={"data": {}}) for step in findings.trail]
    mapped = map_playbook(
        recording.graph, findings.observed.node, incident.direction, findings.anomaly_id, incident.id, trail
    )
    assert mapped is not None and mapped.playbook_id == "revenue_drop" and mapped.finished
    steps = {step.step_id: step for step in mapped.steps}
    assert steps["data_freshness"].trail_steps == [1]
    assert steps["hypothesis_tests"].trail_steps == [9, 10, 11]
    assert steps["planner"].status == "skipped"


@pytest.mark.e2e
def test_live_snapshot_and_semantic_rerun(s1_world: WorldPaths, tmp_path: Path) -> None:
    live = LiveSource(s1_world.world)
    live.runtime.tick(live.runtime.ticks()[0])
    with TestClient(create_app(live, start=False, web_dist=tmp_path)) as client:
        report = MorningReport.model_validate(client.get("/report/morning").json())
        assert report.activity.ticks == 1 and report.activity.series_hours > 0
        assert client.get(report.activity_receipt.href).status_code == 200

    replay = ReplaySource(world=s1_world.world, seconds_per_tick=0)
    with TestClient(create_app(replay, web_dist=tmp_path)) as client:
        report = MorningReport.model_validate(client.get("/report/morning").json())
        impact = next(line for line in report.lines if line.id == "INC-0001:impact")
        proof = impact.receipts[0]
        assert proof.source == "semantic"
        rerun = client.post(proof.rerun_href)
        assert rerun.status_code == 200 and rerun.json()["matches"]
