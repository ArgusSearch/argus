"""Every scenario end to end through the API: the recorded replays and the live runtime over a fresh world.

`fixtures/` holds the S1 run and `fixtures/<scenario>/` the quiet, S2, S3, S4 and S5 runs, all seed 1, recorded
by `make fixtures`. Replay serves each one's story over REST and SSE; the live runtime over a newly generated
world of the same seed streams the same story, so the recordings stay what the runtime does now.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.recording import FIXTURES, Recording, load_recording
from argus.api.sources import LiveSource, ReplaySource
from argus.contracts.events import Event, EventType, InvestigationStepPayload
from mockmart.sim import WorldConfig
from mockmart.world import generate

SEED = 1  # every recording is of seed 1
FAST = 0.001


@dataclass(frozen=True)
class Story:
    incidents: list[tuple[str, str, str]]  # (verdict, root node, final state)
    notes: list[str]  # note kinds, in order
    anomalies: list[str]  # anomaly nodes, in order


STORIES = {
    "quiet": Story(incidents=[], notes=[], anomalies=[]),
    "s1": Story(
        incidents=[("SUPPORTED_CAUSE", "payment_success_rate", "resolved")],
        notes=[],
        anomalies=["payment_success_rate"],
    ),
    "s2": Story(incidents=[], notes=["expected"], anomalies=["ad_spend"]),
    "s3": Story(incidents=[], notes=["data_issue"], anomalies=[]),
    "s4": Story(incidents=[("SUPPORTED_CAUSE", "pacing_ratio", "explained")], notes=[], anomalies=["ad_spend"]),
    "s5": Story(
        incidents=[("SUPPORTED_CAUSE", "payment_success_rate", "resolved")],
        notes=["expected", "expected", "expected"],
        anomalies=["sessions", "orders", "gmv", "payment_success_rate"],
    ),
}
SCENARIOS = sorted(STORIES)


def recording_dir(scenario: str) -> Path:
    return FIXTURES if scenario == "s1" else FIXTURES / scenario


def _sse(client: TestClient, limit: int) -> list[Event]:
    body = client.get(f"/events?limit={limit}").text
    blocks = [b for b in body.split("\n\n") if b.strip() and not b.startswith(":")]
    data = [dict(line.split(": ", 1) for line in b.splitlines() if ": " in line) for b in blocks]
    return [Event.model_validate_json(d["data"]) for d in data if d.get("event") != "stream"]


def _story(client: TestClient, events: list[Event]) -> Story:
    incidents = [(i["verdict"], i["root_node"], i["state"]) for i in client.get("/incidents").json()]
    notes = [e.payload["kind"] for e in events if e.type is EventType.NOTE_LOGGED]
    anomalies = [e.payload["node"] for e in events if e.type is EventType.ANOMALY_OPENED]
    return Story(incidents=incidents, notes=notes, anomalies=anomalies)


def _beat(e: Event) -> tuple[object, ...]:
    """What an event says, without wall-clock timings (which differ between runs)."""
    p = e.payload
    step = p.get("step", {})
    key: dict[EventType, tuple[object, ...]] = {
        EventType.ANOMALY_OPENED: (p.get("id"), p.get("node"), json.dumps(p.get("segment"), sort_keys=True)),
        EventType.INVESTIGATION_STEP: (p.get("anomaly_id"), step.get("kind"), step.get("tool")),
        EventType.INCIDENT_UPDATED: (p.get("id"), p.get("state"), p.get("verdict"), p.get("change")),
        EventType.NOTE_LOGGED: (p.get("kind"), p.get("node")),
        EventType.EDGE_STATUS: (p.get("edge"), p.get("new_status")),
        EventType.TICK: (p.get("hour"), tuple(p.get("pending_nodes", [])), p.get("open_incidents")),
    }
    return (e.seq, e.type.value, e.sim_ts.isoformat(), *key.get(e.type, ()))


@pytest.fixture(scope="module", params=SCENARIOS)
def recorded(request: pytest.FixtureRequest) -> tuple[str, Recording]:
    return request.param, load_recording(recording_dir(request.param))


def test_recording_is_valid_and_cites_only_recorded_receipts(recorded: tuple[str, Recording]) -> None:
    scenario, rec = recorded
    assert rec.manifest["world_start"] and rec.graph.nodes and rec.receipts, scenario
    known = {r.id for r in rec.receipts}
    for event in rec.events:
        if event.type is EventType.INVESTIGATION_STEP:
            step = InvestigationStepPayload.model_validate(event.payload).step
            assert set(step.receipts) <= known, (scenario, step)
        if event.type is EventType.NOTE_LOGGED:
            assert set(event.payload.get("receipts", [])) <= known, (scenario, event.payload)


def test_replay_serves_the_scenario_story(recorded: tuple[str, Recording], tmp_path: Path) -> None:
    scenario, rec = recorded
    source = ReplaySource(recording_dir(scenario), seconds_per_tick=FAST)
    with TestClient(create_app(source, web_dist=tmp_path)) as client:
        assert client.post("/replay", json={"action": "end"}).json()["finished"]
        events = _sse(client, len(rec.events))
        assert [e.type for e in events] == [e.type for e in rec.events]
        assert _story(client, events) == STORIES[scenario]
        for incident in client.get("/incidents").json():
            assert client.get(f"/incidents/{incident['id']}/report").status_code == 200
        digest = client.get("/digest").json()
        assert digest["markdown"].startswith("## While you slept")


@pytest.mark.e2e
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_live_runtime_streams_the_recorded_story(scenario: str, tmp_path: Path) -> None:
    rec = load_recording(recording_dir(scenario))
    world = generate(scenario, WorldConfig(seed=SEED), tmp_path / "world").world
    source = LiveSource(world, seconds_per_tick=0)
    with TestClient(create_app(source, web_dist=tmp_path)) as client:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and not client.get("/health").json()["run"]["finished"]:
            time.sleep(0.2)
        assert client.get("/health").json()["run"]["finished"], f"{scenario}: the live run did not finish"
        assert len(source.bus.history) == len(rec.events), f"{scenario}: re-record with `make fixtures`"
        events = _sse(client, len(rec.events))
        assert _story(client, events) == STORIES[scenario]
        assert [_beat(e) for e in events] == [_beat(e) for e in rec.events], (
            f"{scenario}: the live stream no longer matches fixtures; re-record with `make fixtures`"
        )
        assert source.runtime.fallbacks == []
