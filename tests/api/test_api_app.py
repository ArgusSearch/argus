"""C5 service over the recorded S1 run and a live world: REST, SSE wire format, run control, re-runs."""

from __future__ import annotations

import asyncio
import itertools
import json
import signal
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app, end_streams_on_exit
from argus.api.hub import EventHub
from argus.api.recording import FIXTURES, load_recording
from argus.api.sources import LiveSource, ReplaySource
from argus.api.state import RunState
from argus.contracts.events import Event, EventType
from argus.contracts.findings import IncidentState
from mockmart.world import WorldPaths

FAST = 0.001  # wall seconds per simulated hour


def _blocks(body: str) -> list[dict[str, str]]:
    blocks = [b for b in body.split("\n\n") if b.strip() and not b.startswith(":")]
    return [dict(line.split(": ", 1) for line in b.splitlines() if ": " in line) for b in blocks]


def test_replay_to_end_then_read_everything(tmp_path: Path) -> None:
    with TestClient(create_app(ReplaySource(seconds_per_tick=FAST), web_dist=tmp_path)) as client:
        health = client.get("/health").json()
        assert health["mode"] == "replay" and health["thresholds"]["alarm_z"] > health["thresholds"]["wiggle_z"]
        status = client.post("/replay", json={"action": "end"}).json()
        assert status["finished"] and status["position"] == status["total"]

        assert [i["id"] for i in client.get("/incidents").json()] == ["INC-0001"]
        incident = client.get("/incidents/INC-0001").json()
        assert incident["state"] == "resolved" and incident["findings"]["verdict"] == "SUPPORTED_CAUSE"

        report = client.get("/incidents/INC-0001/report")
        assert report.headers["content-type"].startswith("text/markdown")
        assert report.text.startswith("# SUPPORTED CAUSE") and "## Impact" in report.text

        graph = client.get("/graph").json()
        assert [e for e in graph["edges"] if e["last_test"] is not None], "edge_status events fold into the graph"

        receipt_id = incident["findings"]["root"]["change_pct"]["receipt"]
        assert client.get(f"/receipts/{receipt_id}").json()["sql"].startswith(("WITH", "SELECT"))
        rerun = client.post(f"/receipts/{receipt_id}/rerun")
        assert rerun.status_code == 409 and "make demo" in rerun.json()["detail"]

        digest = client.get("/digest").json()
        keys = {line["key"] for line in digest["lines"]}
        assert {"watched", "wiggles", "held_back", "anomalies", "incident:INC-0001", "edges", "cost"} <= keys
        line = next(line for line in digest["lines"] if line["key"] == "incident:INC-0001")
        assert line["receipts"] and len(set(line["receipts"])) == len(line["receipts"]) and line["tone"] == "good"
        assert digest["markdown"].startswith("## While you slept")

        assert client.get("/incidents/INC-9999").status_code == 404
        assert client.get("/incidents/INC-9999/report").status_code == 404
        assert client.get("/receipts/r99999").status_code == 404
        assert client.post("/replay", json={"speed": 0}).status_code == 422


def test_restart_starts_a_new_stream_after_the_old_seqs(tmp_path: Path) -> None:
    with TestClient(create_app(ReplaySource(seconds_per_tick=FAST), web_dist=tmp_path)) as client:
        client.post("/replay", json={"action": "end"})
        first = client.get("/health").json()
        client.post("/replay", json={"action": "pause"})
        status = client.post("/replay", json={"action": "restart", "speed": 4}).json()
        assert status["speed"] == 4 and status["position"] <= 1
        assert client.get("/incidents").json() == [], "a restart forgets the incidents of the old stream"
        client.post("/replay", json={"action": "end"})
        second = client.get("/health").json()
        assert second["stream"] != first["stream"]
        assert second["last_seq"] == 2 * first["last_seq"], "seq continues after the old stream"
        assert second["events"] == first["events"]


def test_sse_wire_format_resume_and_stream_change() -> None:
    """Without the lifespan the hub is unbound: /events sends the history and ends."""
    source = ReplaySource(seconds_per_tick=FAST)
    events = load_recording(FIXTURES).events[:5]
    for event in events:
        source.bus.publish(event)
    client = TestClient(create_app(source, start=False))
    blocks = _blocks(client.get("/events").text)
    assert len(blocks) == len(events)
    for fields, event in zip(blocks, events, strict=True):
        assert fields["event"] == event.type.value and fields["id"] == str(event.seq)
        assert Event.model_validate_json(fields["data"]) == event

    resumed = _blocks(client.get("/events", headers={"Last-Event-ID": "3"}).text)
    assert [b["id"] for b in resumed] == ["4", "5"]
    assert [b["id"] for b in _blocks(client.get("/events?since=1&limit=2").text)] == ["2", "3"]

    source.bus.reset()
    source.bus.publish(events[0].model_copy(update={"seq": 6}))
    stale = _blocks(client.get("/events", headers={"Last-Event-ID": "5"}).text)
    assert stale[0]["event"] == "stream" and json.loads(stale[0]["data"])["stream"] == source.bus.stream
    assert [b["id"] for b in stale[1:]] == ["6"]


def test_index_without_build_explains_how_to_build(tmp_path: Path) -> None:
    client = TestClient(create_app(ReplaySource(seconds_per_tick=FAST), start=False, web_dist=tmp_path))
    assert "npm --prefix web" in client.get("/").text


def test_replay_serves_incidents_as_of_the_stream() -> None:
    """At every incident_updated event the REST incident already has that event's state, never a later one."""

    async def run() -> list[tuple[str, str | None]]:
        source = ReplaySource(seconds_per_tick=FAST)
        seen: list[tuple[str, str | None]] = []
        source.start()
        async for item in source.bus.follow():
            event = item.event
            assert event is not None
            if event.type is EventType.INCIDENT_UPDATED:
                incidents = source.incidents()
                seen.append((event.payload["state"], incidents[0].state.value if incidents else None))
            elif event.type is EventType.ANOMALY_OPENED:
                assert source.incidents() == []
            if source.status()["finished"] and event.seq == source.bus.last_seq:
                break
        source.stop()
        await source.closed()
        return seen

    seen = asyncio.run(asyncio.wait_for(run(), timeout=30))
    assert seen and all(event == served for event, served in seen)
    assert seen[-1][0] == IncidentState.RESOLVED.value


def test_live_tail_paces_investigation_steps_but_not_the_history() -> None:
    async def run() -> list[float]:
        recording = load_recording(FIXTURES)
        steps = [e for e in recording.events if e.type is EventType.INVESTIGATION_STEP][:5]
        hub = EventHub(RunState(recording.graph))
        hub.bind(asyncio.get_running_loop())
        hub.pace_steps = lambda: 0.05
        for event in steps[:2]:
            hub.publish(event)
        times: list[float] = []

        async def consume() -> None:
            async for _ in hub.follow():
                times.append(time.perf_counter())
                if len(times) == len(steps):
                    return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        for event in steps[2:]:
            hub.publish(event)
        await asyncio.wait_for(task, timeout=5)
        return times

    times = asyncio.run(run())
    assert times[1] - times[0] < 0.02, "history arrives at full speed"
    assert all(b - a >= 0.04 for a, b in itertools.pairwise(times[2:])), "live steps are paced"


@pytest.mark.e2e
def test_replay_reruns_recorded_receipts_on_the_same_world(s1_world: WorldPaths) -> None:
    """The fixtures were recorded on the seed-1 S1 world: their receipts reproduce on a fresh one."""
    source = ReplaySource(seconds_per_tick=FAST, world=s1_world.world)
    client = TestClient(create_app(source, start=False))
    receipts = source.recording.receipts
    for receipt in receipts[:: max(1, len(receipts) // 8)]:
        result = client.post(f"/receipts/{receipt.id}/rerun").json()
        assert result["matches"], result


@pytest.mark.e2e
def test_live_run_control(s1_world: WorldPaths) -> None:
    source = LiveSource(s1_world.world, seconds_per_tick=30)
    with TestClient(create_app(source)) as client:
        deadline = time.time() + 60
        while time.time() < deadline and client.get("/health").json()["run"]["position"] < 1:
            time.sleep(0.1)
        status = client.post("/replay", json={"action": "pause", "speed": 8}).json()
        assert status["position"] >= 1 and status["speed"] == 8 and not status["playing"]
        assert client.post("/replay", json={"action": "restart"}).status_code == 409
        assert client.get("/health").json()["mode"] == "live"
        events = _blocks(client.get("/events?limit=2").text)
        assert [b["id"] for b in events] == ["1", "2"]


def test_exit_signal_ends_every_stream_then_reaches_the_server() -> None:
    """uvicorn waits for open responses before shutting down: the first SIGTERM must end the SSE streams."""
    seen: list[int] = []
    original = signal.signal(signal.SIGTERM, lambda signum, _frame: seen.append(signum))
    try:

        async def run() -> bool:
            hub = EventHub(RunState(load_recording(FIXTURES).graph))
            hub.bind(asyncio.get_running_loop())
            restore = end_streams_on_exit(hub)

            async def consume() -> None:
                async for _ in hub.follow():
                    pass

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.01)
            assert not task.done()
            signal.raise_signal(signal.SIGTERM)
            await asyncio.wait_for(task, timeout=2)
            restore()
            return hub.closed

        assert asyncio.run(run())
        assert seen == [signal.SIGTERM], "the previous handler (uvicorn's) still runs"
    finally:
        signal.signal(signal.SIGTERM, original)
