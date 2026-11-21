"""Inject disconnects and broken recordings through the same interfaces the demo uses."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from datetime import datetime
from pathlib import Path

import httpx2
import pytest

from argus.contracts.events import BenchProgressPayload, Event

from .api_harness import BOUND, ROOT, api_command, frames, recording, serve

pytestmark = pytest.mark.e2e


def test_slow_subscriber_does_not_hold_back_another_client(tmp_path: Path) -> None:
    total = 64
    padding = "x" * (128 * 1024)
    sim_ts = datetime(2026, 11, 21)
    with (tmp_path / "events.jsonl").open("w") as recording_file:
        for seq in range(1, total + 1):
            payload = BenchProgressPayload(run_id="slow-reader", done=seq, total=total, last={"sample": padding})
            recording_file.write(Event.make(seq, sim_ts, payload).model_dump_json() + "\n")

    # An 8 MiB stream and a small TCP receive buffer keep an idle reader from buffering the whole run.
    transport = httpx2.HTTPTransport(trust_env=False, socket_options=[(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)])
    with (
        serve("--replay", str(tmp_path), "--tick-seconds", "30") as server,
        server.client() as control,
        server.client(transport=transport) as slow,
        server.client() as fast,
        slow.stream("GET", "/events", params={"limit": total}) as response,
    ):
        stream = frames(response)
        first = next(stream).event()
        initial = control.get("/health").raise_for_status().json()
        assert not initial["run"]["finished"]

        # Leave the slow subscriber's response open without reading it while another consumes the whole run.
        control.post("/replay", json={"action": "end"}).raise_for_status()
        control.post("/replay", json={"action": "pause"}).raise_for_status()
        with fast.stream("GET", "/events", params={"limit": total}) as other:
            assert [frame.event().seq for frame in frames(other)] == list(range(1, total + 1))
        health = control.get("/health").raise_for_status().json()
        assert health["stream"] == initial["stream"] and health["run"]["finished"]
        assert [first.seq, *(frame.event().seq for frame in stream)] == list(range(1, total + 1))


def test_disconnected_subscriber_resumes_within_the_same_stream() -> None:
    fixture = recording("quiet")
    with serve("--replay", str(fixture), "--tick-seconds", "2") as server, server.client() as client:
        with client.stream("GET", "/events") as response:
            stream = frames(response)
            seen = [next(stream).event().seq for _ in range(5)]
        assert seen == list(range(1, 6))
        end = client.post("/replay", json={"action": "end"}).raise_for_status().json()
        client.post("/replay", json={"action": "pause"}).raise_for_status()
        total = end["total"]
        headers = {"Last-Event-ID": str(seen[-1])}
        with client.stream("GET", "/events", headers=headers, params={"limit": total - len(seen)}) as resumed:
            assert [frame.event().seq for frame in frames(resumed)] == list(range(6, total + 1))


def test_replay_restart_sends_stream_reset_to_old_cursor() -> None:
    fixture = recording("quiet")
    with serve("--replay", str(fixture), "--tick-seconds", "2") as server, server.client() as client:
        initial = client.get("/health").raise_for_status().json()
        end = client.post("/replay", json={"action": "end"}).raise_for_status().json()
        client.post("/replay", json={"action": "restart"}).raise_for_status()
        new = client.get("/health").raise_for_status().json()
        assert new["stream"] != initial["stream"]

        with client.stream("GET", "/events?limit=1", headers={"Last-Event-ID": str(end["total"])}) as response:
            reset, first = frames(response)
            assert reset.name == "stream" and reset.id is None
            assert json.loads(reset.data) == {"stream": new["stream"], "mode": "replay"}
            assert first.event().seq == end["total"] + 1


def test_killed_api_recovers_with_a_fresh_stream() -> None:
    source = ("--replay", str(recording("quiet")), "--tick-seconds", "2")
    with (
        serve(*source) as server,
        server.client() as control,
        server.client() as subscriber,
        subscriber.stream("GET", "/events") as response,
    ):
        old_stream = control.get("/health").raise_for_status().json()["stream"]
        stream = frames(response)
        assert next(stream).event().seq == 1
        server.process.kill()
        assert server.process.wait(timeout=5) != 0
        # The server died mid-response. Consume any kernel-buffered frames before checking the disconnect.
        with pytest.raises((httpx2.RemoteProtocolError, httpx2.ReadError)):
            list(stream)

    with serve(*source) as server, server.client() as client:
        health = client.get("/health").raise_for_status().json()
        assert health["stream"] != old_stream
        # A cursor is usable only with the stream ID the client originally observed.
        with client.stream("GET", "/events?limit=1") as response:
            (first,) = frames(response)
            assert first.event().seq == 1


@pytest.mark.parametrize("fault", ["missing", "malformed_json", "invalid_payload", "duplicate_seq"])
def test_invalid_recording_is_rejected_before_listening(tmp_path: Path, fault: str) -> None:
    target = tmp_path / "events.jsonl"
    original = (recording("quiet") / target.name).read_text().splitlines()
    first, second = original[:2]
    match fault:
        case "missing":
            diagnostic = f"no events.jsonl in {tmp_path}"
        case "malformed_json":
            target.write_text(first + "\n{\n")
            diagnostic = "JSONDecodeError"
        case "invalid_payload":
            invalid = {**json.loads(second), "payload": {}}
            target.write_text(first + "\n" + json.dumps(invalid) + "\n")
            diagnostic = "ValidationError"
        case "duplicate_seq":
            duplicate = {**json.loads(second), "seq": json.loads(first)["seq"]}
            target.write_text(first + "\n" + json.dumps(duplicate) + "\n")
            diagnostic = "event seq must be strictly increasing"
        case _:
            pytest.fail(f"unknown fault {fault}")

    run = subprocess.run(
        api_command("--replay", str(tmp_path)), cwd=ROOT, capture_output=True, text=True, timeout=15, check=False
    )
    output = run.stdout + run.stderr
    assert run.returncode != 0, output
    assert BOUND.search(output) is None, output
    assert diagnostic in output, output


class MissingEvidence(AssertionError):
    """The specific replay health defect tracked in the robustness report."""


@pytest.mark.xfail(strict=True, raises=MissingEvidence, reason="Replay reports healthy with a dangling receipt")
def test_missing_receipt_fixture_never_advertises_a_healthy_incomplete_demo(tmp_path: Path) -> None:
    source = tmp_path / "s1"
    source.mkdir()
    for name in ("events.jsonl", "graph.json", "manifest.json", "incidents.json"):
        shutil.copyfile(recording("s1") / name, source / name)
    with serve("--replay", str(source), "--tick-seconds", "2") as server, server.client() as client:
        client.post("/replay", json={"action": "end"}).raise_for_status()
        incident = client.get("/incidents").raise_for_status().json()[0]
        receipt = incident["findings"]["root"]["change_pct"]["receipt"]
        evidence = client.get(f"/receipts/{receipt}")
        health = client.get("/health").raise_for_status().json()
        if evidence.status_code == 404 and health["status"] == "ok":
            raise MissingEvidence(f"healthy replay serves an incident whose receipt {receipt} returns 404")
        assert evidence.status_code == 200 or health["status"] != "ok", (receipt, evidence.status_code, health)
