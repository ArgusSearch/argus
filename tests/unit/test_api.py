"""API: REST routes and the SSE stream, in replay mode (fixtures) and live mode (a world)."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.sources import LiveSource, ReplaySource
from argus.contracts.events import ROUTES, Event
from mockmart.world import WorldPaths


def _sse_events(client: TestClient, url: str) -> list[Event]:
    events = []
    with client.stream("GET", url) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(Event.model_validate_json(line[len("data: ") :]))
    return events


def test_replay_mode_serves_the_recorded_run() -> None:
    source = ReplaySource(seconds_per_tick=0)
    with TestClient(create_app(source)) as client:
        assert client.get("/health").json()["mode"] == "replay"
        graph = client.get("/graph").json()
        assert len(graph["nodes"]) > 20
        incidents = client.get("/incidents").json()
        assert incidents and incidents[0]["verdict"] == "SUPPORTED_CAUSE"
        inc_id = incidents[0]["id"]
        detail = client.get(f"/incidents/{inc_id}").json()
        assert detail["findings"]["trail"]
        report = client.get(f"/incidents/{inc_id}/report").text
        assert report.startswith("# SUPPORTED CAUSE")
        rid = detail["findings"]["root"]["change_pct"]["receipt"]
        assert client.get(f"/receipts/{rid}").json()["sql"].startswith(("WITH", "SELECT"))
        assert client.post(f"/receipts/{rid}/rerun").status_code == 409
        assert client.get("/incidents/INC-9999").status_code == 404
        for _ in range(50):
            if len(source.bus.history) >= 5:
                break
            time.sleep(0.05)
        events = _sse_events(client, "/events?limit=5")
        assert [e.seq for e in events] == [1, 2, 3, 4, 5]
        assert _sse_events(client, "/events?since=3&limit=2")[0].seq == 4


def test_stub_routes_answer_501_with_their_owner() -> None:
    with TestClient(create_app(ReplaySource(seconds_per_tick=0), start=False)) as client:
        for route in [r for r in ROUTES if r.status == "stub"]:
            path = route.path.replace("{id}", "INC-0001")
            resp = client.request(route.method, path)
            assert resp.status_code == 501, route.path
            assert resp.json()["owner"] == f"lane {route.owner}"


def test_live_mode_runs_argus_over_a_world_and_reruns_receipts(s1_world: WorldPaths) -> None:
    source = LiveSource(s1_world.world, seconds_per_tick=0)
    with TestClient(create_app(source)) as client:
        deadline = time.time() + 60
        while time.time() < deadline and not client.get("/incidents").json():
            time.sleep(0.2)
        incidents = client.get("/incidents").json()
        assert incidents, "the live runtime opened no incident"
        source.stop()
        detail = client.get(f"/incidents/{incidents[0]['id']}").json()
        receipts = {s for step in detail["findings"]["trail"] for s in step["receipts"]}
        assert receipts
        for rid in sorted(receipts):
            body = client.post(f"/receipts/{rid}/rerun").json()
            assert body["matches"], body
        events = _sse_events(client, "/events?limit=3")
        assert events[0].type.value in ("edge_status", "tick")
        assert json.loads(events[0].model_dump_json())["seq"] == 1
