"""The public origin uses OpenAI's HTTP adapter and keeps visitor runs bounded and private."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from argus.agent.provider import OPENAI_ASTRA, OPENAI_SOL, ProviderUnavailable
from argus.agent.types import LlmRequest
from argus.api.public_limits import BUDGET_MESSAGE, MAX_INPUT_TOKENS, PublicLimits, public_provider
from argus.remediation.api import OperatorGate

TEST_TOKEN = "local-test-token"
ANSWER = "I checked the latest available shop data."


class FakeResponses(BaseHTTPRequestHandler):
    """A local OpenAI-shaped server for the API and browser checks."""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        if self.path != "/v1/responses" or self.headers.get("Authorization") != f"Bearer {TEST_TOKEN}":
            self.send_error(403)
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        tools = {tool["name"] for tool in request["tools"]}
        if "answer" in tools:
            name, arguments = "answer", {"text": ANSWER, "claims": []}
        elif "submit_challenge" in tools:
            name, arguments = "submit_challenge", {"opinion": "upheld", "summary": "The evidence stands."}
        else:
            name, arguments = "submit_findings", {"verdict": "SUPPORTED_CAUSE", "summary": "Check the event evidence."}
        result = json.dumps(
            {
                "model": request["model"],
                "status": "completed",
                "usage": {"input_tokens": 1200, "output_tokens": 130},
                "output": [
                    {
                        "type": "function_call",
                        "name": name,
                        "arguments": json.dumps(arguments),
                        "call_id": f"fake_{uuid4().hex}",
                    }
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[str]:
    with ThreadingHTTPServer(("127.0.0.1", 0), FakeResponses) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}/v1"
        monkeypatch.setenv("ARGUS_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", TEST_TOKEN)
        monkeypatch.setenv("ARGUS_PUBLIC_OPENAI_BASE_URL", base)
        monkeypatch.setenv("ARGUS_SPEND_LEDGER", str(tmp_path / "spend.jsonl"))
        monkeypatch.delenv("ARGUS_DISABLE_PROVIDER", raising=False)
        try:
            yield base
        finally:
            server.shutdown()
            worker.join()


def operator(client: TestClient) -> dict[str, str]:
    response = client.post("/agent/operator/session")
    assert response.status_code == 200
    return {"X-Argus-CSRF": response.json()["csrf_token"]}


@pytest.mark.e2e
def test_public_live_provider_and_visitor_limits(
    fake_openai: str, s1_world, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    from scripts.cloudflare_api import origin_app

    monkeypatch.setenv("ARGUS_PUBLIC_DAILY_USD", "0.50")
    monkeypatch.setattr("argus.api.public_limits.SESSION_HOUR", 2)
    monkeypatch.setattr("argus.api.public_limits.IP_HOUR", 3)
    app = origin_app(s1_world.world, state_dir=tmp_path / "public")
    opts = {"base_url": "https://localhost", "client": ("127.0.0.1", 1234)}
    question = {"question": "What changed in the shop?"}
    with TestClient(app, **opts) as first, closing(TestClient(app, **opts)) as second:
        ready = time.monotonic() + 45
        while first.get("/health").json()["run"]["position"] < 1:
            assert time.monotonic() < ready
            time.sleep(0.5)
        health = first.get("/agent/health").json()
        assert health["mode"] == "live" and health["enabled"]
        assert health["models"]["loop"] == OPENAI_SOL
        assert health["models"]["critic"] == OPENAI_ASTRA
        assert TEST_TOKEN not in json.dumps(health)
        assert first.post("/replay", json={"action": "pause"}).status_code == 403
        assert first.post("/sealed-run/replay", json={"action": "pause"}).status_code == 200
        assert first.post("/agent/ask", json=question).status_code == 403
        one, two = operator(first), operator(second)
        reply = first.post("/agent/ask", json=question, headers=one)
        assert reply.status_code == 200, reply.text
        answer = reply.json()
        assert answer["status"] == "answered" and answer["answer"] == ANSWER
        assert question["question"] in first.get("/agent/activity").text
        assert question["question"] not in second.get("/agent/activity").text
        assert answer["run_id"] not in second.get("/agent/runs").text
        follow_up = {**question, "conversation_id": answer["conversation_id"]}
        assert second.post("/agent/ask", json=follow_up, headers=two).status_code == 404
        assert first.post("/agent/ask", json=follow_up, headers=one).status_code == 200
        limited = first.post("/agent/ask", json=question, headers=one)
        assert limited.status_code == 429 and "session" in limited.json()["detail"]
        with closing(TestClient(app, **opts)) as third:
            limited = third.post("/agent/ask", json=question, headers=operator(third))
            assert limited.status_code == 429 and "connection" in limited.json()["detail"]

        ledger = tmp_path / "spend.jsonl"
        charges = [json.loads(line) for line in ledger.read_text().splitlines()]
        assert len(charges) == 2 and all(charge["model"] == OPENAI_SOL for charge in charges)
        assert 0 < first.get("/agent/health").json()["public_limits"]["spent_today_usd"] < 0.50
        with ledger.open("a") as file:
            file.write(json.dumps({"task": "argus-agent", "usd": 0.50, "ts": int(time.time())}) + "\n")
        with closing(TestClient(app, **opts)) as fourth:
            limited = fourth.post("/agent/ask", json=question, headers=operator(fourth))
            assert limited.status_code == 429 and limited.json()["detail"] == BUDGET_MESSAGE
        assert first.get("/agent/health").json()["public_limits"]["message"] == BUDGET_MESSAGE


def test_daily_reservations_survive_concurrency_and_a_restart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARGUS_PUBLIC_DAILY_USD", "0.50")
    monkeypatch.delenv("ARGUS_SPEND_LEDGER", raising=False)
    limits = PublicLimits(tmp_path, OperatorGate())

    def reserve() -> bool:
        try:
            limits.reserve(0.30, starts_investigation=False)
        except ProviderUnavailable:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: reserve(), range(2))) == 1
    restarted = PublicLimits(tmp_path, OperatorGate())
    with pytest.raises(ProviderUnavailable, match="budget"):
        restarted.reserve(0.30, starts_investigation=False)


def test_metering_rejects_oversized_and_over_turn_calls(fake_openai: str, tmp_path: Path) -> None:
    limits = PublicLimits(tmp_path, OperatorGate())
    client, _ = public_provider(limits, None)
    request = LlmRequest(
        model=OPENAI_SOL,
        system="Shop monitor",
        messages=[],
        tools=[],
        max_tokens=1,
        key="ask:case:1",
    )
    with pytest.raises(ProviderUnavailable, match="input limit"):
        client.create(request.model_copy(update={"system": "x" * MAX_INPUT_TOKENS}))
    with pytest.raises(ProviderUnavailable, match="turn or output"):
        client.create(request.model_copy(update={"key": "ask:case:7"}))
    with pytest.raises(ProviderUnavailable, match="turn or output"):
        client.create(request.model_copy(update={"max_tokens": 3001}))
    assert not (tmp_path / "spend.jsonl").exists()
