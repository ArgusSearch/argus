"""The demo walkthrough uses the actual S2 planned-change note without opening an incident."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from argus.api.hub import EventHub
from argus.api.state import RunState
from argus.demo.api import create_router
from argus.demo.contracts import ExpectedChange
from argus.demo.playback import Playback
from argus.demo.timeline import load_timeline


def test_showcase_order_and_expected_change_cut() -> None:
    expected = load_timeline("s2")
    note = expected.cues[1].data
    assert isinstance(note, ExpectedChange)
    assert note.note.payload["segment"]["country"] == "FR"
    assert note.note.payload["kind"] == "expected"
    assert "cal_adv_01_FR_push" in note.note.payload["reason"]
    receipt = note.note.payload["receipts"][0]

    now = 0.0
    app = FastAPI()
    playback = Playback(clock=lambda: now)
    app.include_router(create_router(EventHub(RunState(expected.graph)), allow_agent=True, playback=playback))
    with TestClient(app) as client:
        chapters = client.get("/demo/showcase").json()
        assert [chapter["id"] for chapter in chapters] == ["fault", "expected_change", "metric_placement", "agent"]
        assert chapters[0]["start"]["scenario"] == "s1"
        assert chapters[2]["path"] == "/graph/metrics" and chapters[2]["expected"] == ["EXACT", "AMBIGUOUS"]
        assert chapters[3]["start"]["variant"] == "agent" and chapters[3]["start"]["scenario"] == "s4"
        assert client.post("/demo/start", json={"scenario": "s2", "variant": "agent"}).status_code == 422

        started = client.post("/demo/start", json=chapters[1]["start"]).json()
        params = {"run_id": started["run_id"]}
        assert started["duration_ms"] == 12_000
        early = client.get("/demo/snapshot", params=params).json()
        assert early["events"][-1]["seq"] < note.note.seq
        assert client.get(f"/demo/receipts/{receipt}", params=params).status_code == 404
        now += 4
        shown = client.get("/demo/snapshot", params=params).json()
        assert shown["events"][-1] == note.note.model_dump(mode="json")
        assert shown["incidents"] == []
        assert client.get(f"/demo/receipts/{receipt}", params=params).json()["id"] == receipt
        assert client.get("/demo/counterfactual", params=params).status_code == 404
        now += 8
        assert client.get("/demo/state").json()["status"] == "completed"
        stream = client.get("/demo/events", params=params).text
        assert '"kind":"expected_change"' in stream and "event: complete" in stream
        assert "action_proposed" not in stream
