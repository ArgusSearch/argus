"""Verify every demo story with a connected SSE client while the real API is producing events."""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from pydantic import TypeAdapter

from argus.contracts.events import EdgeStatusPayload, Event, EventType
from argus.contracts.findings import Incident, Note, Receipt, Verdict
from argus.contracts.graph import Graph
from mockmart.sim import WorldConfig
from mockmart.world import generate

from .api_harness import RECORDING_SEED, SCENARIOS, TIMEOUT, frames, recording, serve

EXPECTATIONS = json.loads((Path(__file__).parent / "fixtures" / "scenario_expectations.json").read_text())
LIVE_STREAM_TIMEOUT = 240  # DuckDB computes every live tick, which can take several minutes on a busy host.


@pytest.fixture
def demo_source(mode: str, scenario: str) -> Iterator[tuple[str, str]]:
    if mode == "live":
        with tempfile.TemporaryDirectory(prefix="argus-live-test-") as tmp:
            world = generate(scenario, WorldConfig(seed=RECORDING_SEED), Path(tmp)).world
            yield "--world", str(world)
    else:
        yield "--replay", str(recording(scenario))


def assert_story(client: httpx2.Client, events: list[Event], scenario: str, mode: str) -> None:
    story = EXPECTATIONS[scenario]
    anomalies = [event.payload["node"] for event in events if event.type is EventType.ANOMALY_OPENED]
    updates = [event.payload for event in events if event.type is EventType.INCIDENT_UPDATED]
    notes = [Note.model_validate(event.payload) for event in events if event.type is EventType.NOTE_LOGGED]
    assert anomalies == story["anomalies"]
    assert [update["state"] for update in updates] == story["incident_states"]
    assert [note.kind for note in notes] == story["notes"]
    assert TypeAdapter(list[Note]).validate_python(client.get("/notes").raise_for_status().json()) == notes[::-1]
    if scenario == "s3":
        ticks = [e.payload for e in events if e.type is EventType.TICK and e.sim_ts >= notes[0].sim_ts]
        assert "orders" in ticks[0]["pending_nodes"] and "orders" not in ticks[0]["scored_nodes"]
        assert any("orders" in tick["scored_nodes"] for tick in ticks[1:])

    incidents = TypeAdapter(list[Incident]).validate_python(client.get("/incidents").raise_for_status().json())
    if not updates:
        assert not incidents
        return
    (incident,) = incidents
    assert Incident.model_validate(client.get(f"/incidents/{incident.id}").raise_for_status().json()) == incident
    assert incident.state.value == updates[-1]["state"]
    assert incident.verdict is Verdict.SUPPORTED_CAUSE
    assert incident.root_node == story["root"]
    assert incident.segment == story["segment"]
    root = incident.findings.root
    assert root and root.evidence and root.evidence.ref == story["cause"]
    if scenario == "s1":
        assert any(
            item.evidence and item.evidence.ref == "dep_android-app_8.3.0" and "holdout" in item.reason
            for item in incident.findings.ruled_out
        )
    report = client.get(f"/incidents/{incident.id}/report").raise_for_status()
    assert report.headers["content-type"].startswith("text/markdown")
    assert report.text.startswith("# SUPPORTED CAUSE")
    receipt_id = root.change_pct.receipt
    assert receipt_id
    receipt = Receipt.model_validate(client.get(f"/receipts/{receipt_id}").raise_for_status().json())
    rerun = client.post(f"/receipts/{receipt.id}/rerun")
    if mode == "live":
        result = rerun.raise_for_status().json()
        assert result["matches"] and result["result_hash"] == receipt.result_hash
    else:
        assert rerun.status_code == 409


@pytest.mark.e2e
@pytest.mark.parametrize("mode", ["replay", "live"])
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_demo_stream_over_http(demo_source: tuple[str, str], mode: str, scenario: str) -> None:
    stream_timeout = LIVE_STREAM_TIMEOUT if mode == "live" else TIMEOUT
    fixture = recording(scenario)
    recorded = [Event.model_validate_json(line) for line in (fixture / "events.jsonl").read_text().splitlines()]
    expected_graph = Graph.model_validate_json((fixture / "graph.json").read_bytes())
    manifest = json.loads((fixture / "manifest.json").read_text())
    with (
        serve(*demo_source) as server,
        server.client() as control,
        server.client(read_timeout=stream_timeout) as subscriber,
        subscriber.stream("GET", "/events", params={"limit": len(recorded)}) as response,
    ):
        stream = frames(response, timeout=stream_timeout)
        first = next(stream).event()
        initial = control.get("/health").raise_for_status().json()
        assert initial["mode"] == mode and not initial["run"]["finished"]
        if mode == "live":
            assert control.post("/replay", json={"action": "restart"}).status_code == 409
        control.post("/replay", json={"action": "end"}).raise_for_status()
        if mode == "replay":
            control.post("/replay", json={"action": "pause"}).raise_for_status()
        events = [first, *(frame.event() for frame in stream)]

        deadline = time.monotonic() + stream_timeout
        while not (health := control.get("/health").raise_for_status().json())["run"]["finished"]:
            assert time.monotonic() < deadline, health
            time.sleep(0.01)
        assert health["stream"] == initial["stream"]
        assert health["events"] == health["last_seq"] == len(recorded)
        assert health["run"]["position"] == health["run"]["total"]
        assert [event.seq for event in events] == list(range(1, len(recorded) + 1))
        if mode == "replay":
            assert events == recorded
        else:
            assert [(e.type, e.sim_ts) for e in events] == [(e.type, e.sim_ts) for e in recorded]

        start = datetime.fromisoformat(manifest["live_start"])
        end = datetime.fromisoformat(manifest["world_end"])
        count = int((end - start) / timedelta(hours=1))
        ticks = [datetime.fromisoformat(e.payload["hour"]) for e in events if e.type is EventType.TICK]
        assert ticks == [start + timedelta(hours=hour) for hour in range(count)]

        graph = Graph.model_validate(control.get("/graph").raise_for_status().json())
        assert graph.nodes == expected_graph.nodes
        assert graph.logs == expected_graph.logs
        assert {(e.id, e.kind, e.target, tuple(e.sources)) for e in graph.edges} == {
            (e.id, e.kind, e.target, tuple(e.sources)) for e in expected_graph.edges
        }
        changes = [EdgeStatusPayload.model_validate(e.payload) for e in events if e.type is EventType.EDGE_STATUS]
        latest = {change.edge: change for change in changes}
        assert latest
        for edge_id, change in latest.items():
            edge = graph.edge(edge_id)
            assert edge.status == change.new_status
            if mode == "replay":
                assert edge.last_test == change.result
            else:
                # Live retests can refresh a result without publishing another status event.
                recorded_result = expected_graph.edge(edge_id).last_test
                assert edge.last_test is not None and recorded_result is not None
                assert edge.last_test.ran_at == recorded_result.ran_at
                assert edge.last_test.passed == recorded_result.passed
        assert_story(control, events, scenario, mode)
