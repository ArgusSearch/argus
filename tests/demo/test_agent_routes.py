"""The replay server plays the sealed S4 agent presentation through the agent routes the web calls.

Mission Control pins every `/agent/*` request to the presentation with `run_id` (web/src/lib/agent.ts `withRun`):
activity, actions, Ask and receipts read the presentation at its clock, and approval goes through the same local
operator session as a live run before the paused clock moves on.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.sources import ReplaySource

REPO = Path(__file__).resolve().parents[2]
QUESTION = "Could higher traffic explain the spend?"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("ARGUS_DEMO_BUNDLE", raising=False)
    monkeypatch.delenv("ARGUS_DEMO_BUNDLE_SHA", raising=False)
    # the operator session opens only from the local machine
    return TestClient(create_app(ReplaySource(REPO / "fixtures" / "s4"), start=False), client=("127.0.0.1", 50000))


def _to_approval(client: TestClient, run_id: str) -> None:
    for _ in range(20):
        if client.get("/demo/state").json()["status"] == "awaiting_approval":
            return
        assert client.post("/demo/control", params={"run_id": run_id}, json={"action": "skip"}).status_code == 200
    raise AssertionError("the presentation never reached its approval")


def test_replay_serves_the_agent_presentation_and_its_approval(client: TestClient) -> None:
    with client:
        assert "/demo/snapshot" in client.get("/openapi.json").json()["paths"]
        started = client.post("/demo/start", json={"scenario": "s4", "variant": "agent", "speed": 1})
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]
        run = {"run_id": run_id}
        _to_approval(client, run_id)

        activity = client.get("/agent/activity", params=run).json()
        assert activity["stream"] == f"demo:{run_id}" and activity["mode"] == "replay"
        assert any(r["kind"] == "tool_call" for r in activity["records"])
        last = activity["records"][-1]["seq"]
        assert client.get("/agent/activity", params={**run, "since": last}).json()["records"] == []

        [investigation] = client.get("/agent/runs", params=run).json()
        assert investigation["mode"] == "replay" and investigation["status"] == "done"
        assert investigation["llm_calls"] == 4 and investigation["tool_calls"] == 3
        assert investigation["usd"] == pytest.approx(0.045867)

        [pending] = client.get("/agent/actions", params=run).json()
        assert pending["state"] == "AWAIT_OPERATOR"
        assert client.get(f"/agent/actions/{pending['id']}", params=run).json()["id"] == pending["id"]
        assert client.get("/agent/actions/nope", params=run).status_code == 404

        answer = client.post("/agent/ask", params=run, json={"question": QUESTION}).json()
        assert answer["status"] == "answered" and answer["receipt_links"]
        for link in answer["receipt_links"]:
            path = f"/agent/receipts/{link['run_id']}/{link['world_revision']}/{link['receipt_id']}"
            proof = client.get(path, params=run)
            assert proof.status_code == 200, path
            assert "verified_at_capture" in proof.json()

        decision = {"digest": pending["digest"], "idempotency_key": "click-0001"}
        approve = f"/agent/actions/{pending['id']}/approve"
        assert client.post(approve, params=run, json=decision).status_code == 403  # no operator session
        token = client.post("/agent/operator/session", json={}).json()["csrf_token"]
        decided = client.post(approve, params=run, json=decision, headers={"X-Argus-CSRF": token})
        assert decided.status_code == 200, decided.text
        assert decided.json()["id"] == pending["id"]
        state = client.get("/demo/state").json()
        assert state["decision"] == "approve" and state["status"] == "playing"
        # the same click again is idempotent; a different decision on the decided action is refused
        again = client.post(approve, params=run, json=decision, headers={"X-Argus-CSRF": token})
        assert again.status_code == 200
        other = {**decision, "idempotency_key": "click-0002"}
        deny = f"/agent/actions/{pending['id']}/deny"
        assert client.post(deny, params=run, json=other, headers={"X-Argus-CSRF": token}).status_code == 409

        # outside the presentation the routes keep their replay answers; a replaced run is refused
        assert client.get("/agent/actions").json() == []
        assert client.get("/agent/activity", params={"run_id": "replaced"}).status_code == 409


def test_custom_recording_still_requires_its_digest(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGUS_DEMO_BUNDLE", str(REPO / "fixtures" / "agent" / "v1" / "s4"))
    with client:
        response = client.post("/demo/start", json={"scenario": "s4", "variant": "agent"})
        assert response.status_code == 503
        assert "configure ARGUS_DEMO_BUNDLE_SHA" in response.json()["detail"]
