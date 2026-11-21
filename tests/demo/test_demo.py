"""Demo playback through the same recording, API, and CLI used by Mission Control."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.sources import ReplaySource
from argus.demo.contracts import AnomalyAppears, DemoBeat, InvestigationSteps, MorningReport, QuietWorld, VerdictBeat
from argus.demo.playback import ControlError, Playback
from argus.demo.timeline import DURATION_MS, load_timeline

WIRE = json.loads((Path(__file__).parent / "fixtures" / "timeline-v1.json").read_text())


@pytest.mark.parametrize(
    ("scenario", "detected_node", "root_node", "evidence_ref"),
    [
        ("s1", "payment_success_rate", "payment_success_rate", "ps_payco_degraded"),
        ("s4", "ad_spend", "pacing_ratio", "dep_ad-pacer_1.7.0"),
    ],
)
def test_timeline_uses_recorded_story(scenario: str, detected_node: str, root_node: str, evidence_ref: str) -> None:
    timeline = load_timeline(scenario)
    assert WIRE["duration_ms"] == DURATION_MS
    assert [cue.model_dump(include={"at_ms", "kind", "duration_ms"}) for cue in timeline.cues] == WIRE["beats"]
    assert [cue.sim_ts for cue in timeline.cues] == sorted(cue.sim_ts for cue in timeline.cues)

    quiet, anomaly, _, opening, localize, hypotheses, _, verdict, morning = (cue.data for cue in timeline.cues)
    assert isinstance(quiet, QuietWorld) and quiet.quiet_hours > 0
    assert isinstance(anomaly, AnomalyAppears) and quiet.tick.sim_ts < anomaly.anomaly.sim_ts
    assert anomaly.anomaly.payload["node"] == detected_node
    opening_phases = [opening, localize, hypotheses]
    assert all(isinstance(phase, InvestigationSteps) and phase.steps for phase in opening_phases)
    assert [phase.phase for phase in opening_phases] == ["opening", "localize", "hypotheses"]

    assert isinstance(verdict, VerdictBeat)
    assert verdict.outcome == "SUPPORTED_CAUSE"
    assert verdict.calendar_check.payload["step"]["kind"] == "calendar"
    assert verdict.incident.root_node == root_node
    root = verdict.incident.findings.root
    assert root and root.evidence and root.evidence.ref == evidence_ref
    assert root.change_pct.receipt in timeline.receipts
    assert isinstance(morning, MorningReport)
    assert morning.digest.until and morning.digest.until.hour == 8
    assert any(line.key == f"incident:{verdict.incident.id}" for line in morning.digest.lines)


def test_clock_speed_pause_skip_resume_and_restart() -> None:
    now = 100.0
    playback = Playback(clock=lambda: now)
    assert playback.state().status == "idle"
    with pytest.raises(ControlError):
        playback.control("skip")
    started = playback.start(load_timeline("s4"), speed=2.0)
    assert started.beat_index == 0
    now += 5.5
    assert playback.state().elapsed_ms == 11_000
    assert playback.state().beat_index == 0
    now += 0.5
    assert playback.state().beat_index == 1

    paused = playback.control("pause")
    now += 120
    assert playback.state() == paused
    skipped = playback.control("skip")
    assert (skipped.status, skipped.elapsed_ms, skipped.beat_index) == ("paused", 21_000, 2)
    playback.control("resume")
    now += 4.5
    assert (playback.state().beat_index, playback.state().elapsed_ms) == (3, 30_000)
    now += 30
    assert (playback.state().status, playback.state().elapsed_ms) == ("completed", 90_000)
    with pytest.raises(ControlError):
        playback.control("skip")
    restarted = playback.control("restart")
    assert restarted.run_id != started.run_id
    assert (restarted.scenario, restarted.speed, restarted.status, restarted.beat_index) == ("s4", 2, "playing", 0)


def _frames(body: str) -> list[dict[str, str]]:
    return [
        dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        for block in body.split("\n\n")
        if block.startswith(("event:", "id:"))
    ]


def test_sse_playback_and_resume_through_argus_app() -> None:
    with TestClient(create_app(ReplaySource(), start=False)) as client:
        assert client.get("/demo/state").json()["status"] == "idle"
        assert client.get("/demo/events").status_code == 409
        assert client.post("/demo/start", json={"scenario": "s3"}).status_code == 422
        assert client.post("/demo/start", json={"speed": 0}).status_code == 422
        started = client.post("/demo/start", json={"scenario": "s4", "speed": 100}).json()
        run_id = started["run_id"]
        path = f"/demo/events?run_id={run_id}"
        stream = client.get(path)
        assert stream.headers["content-type"].startswith("text/event-stream")
        frames = _frames(stream.text)
        assert [frame["event"] for frame in frames] == ["beat"] * 9 + ["complete"]
        beats = [DemoBeat.model_validate_json(frame["data"]) for frame in frames[:-1]]
        assert [beat.model_dump(include={"at_ms", "kind", "duration_ms"}) for beat in beats] == WIRE["beats"]
        assert all(beat.run_id == run_id and beat.scenario == "s4" for beat in beats)
        assert [frame["id"] for frame in frames[:-1]] == [f"{run_id}:{i}" for i in range(len(beats))]
        completed = json.loads(frames[-1]["data"])
        assert completed == client.get("/demo/state").json()
        assert completed["status"] == "completed" and completed["elapsed_ms"] == 90_000

        resumed = client.get(path, headers={"Last-Event-ID": frames[6]["id"]})
        assert _frames(resumed.text) == frames[7:]
        assert client.post("/demo/control", json={"action": "pause"}).status_code == 409
        newer = client.post("/demo/control", json={"action": "restart"}).json()
        assert newer["run_id"] != run_id
        assert client.get(path).status_code == 204
        assert client.get("/demo/events", headers={"Last-Event-ID": frames[6]["id"]}).status_code == 204


def test_skip_and_receipts_follow_the_recorded_cues() -> None:
    with TestClient(create_app(ReplaySource(), start=False)) as client:
        run = client.post("/demo/start", json={"scenario": "s1"}).json()
        graph = client.get("/demo/graph", params={"run_id": run["run_id"]}).json()
        assert any(node["id"] == "payment_success_rate" for node in graph["nodes"])
        anomaly = load_timeline("s1").cues[1].data
        assert isinstance(anomaly, AnomalyAppears)
        receipt_id = anomaly.anomaly.payload["receipts"][0]
        receipt_path = f"/demo/receipts/{receipt_id}"
        assert client.get(receipt_path).status_code == 404

        assert client.post("/demo/control", json={"action": "pause"}).json()["status"] == "paused"
        for index in range(1, 9):
            step = client.post("/demo/control", json={"action": "skip"}).json()
            assert (step["status"], step["beat_index"]) == ("paused", index)
            assert step["elapsed_ms"] == WIRE["beats"][index]["at_ms"]
            assert client.get(receipt_path).json()["id"] == receipt_id
        assert client.post("/demo/control", json={"action": "skip"}).json()["status"] == "completed"
        assert [frame["event"] for frame in _frames(client.get("/demo/events").text)] == ["beat"] * 9 + ["complete"]


def test_cli_dry_run() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "argus.cli", "demo", "--scenario", "s4", "--speed", "2"],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.splitlines()
    assert lines[0] == "S4 demo at 2x"
    assert [line.split()[1] for line in lines[1:-1]] == [beat["kind"] for beat in WIRE["beats"]]
    assert lines[-1].split() == ["45.00s", "completed"]
