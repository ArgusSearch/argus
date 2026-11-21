"""The /agent routes over a live S1 run, with a scripted model: health, activity, Ask with verified claims."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from argus.agent.ask import AskRunner
from argus.agent.fake import FakeLlmClient
from argus.agent.journal import Journal
from argus.agent.service import AgentService
from argus.agent.types import LlmRequest, LlmResponse
from argus.api.app import create_app
from argus.api.sources import LiveSource
from argus.evidence import EvidenceStore
from mockmart.world import WorldPaths

pytestmark = pytest.mark.e2e
SEGMENT = {"country": "DE", "platform": "android", "provider": "PayCo"}
HOUR = "2026-11-21T18:00:00"


def reply(name: str, args: dict[str, Any], n: int, text: str = "") -> LlmResponse:
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    blocks.append({"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": args})
    usage = {"input_tokens": 500, "output_tokens": 40, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return LlmResponse(model="claude-sonnet-5-5", content=blocks, stop_reason="tool_use", usage=usage)


def asker(answer_text: str) -> FakeLlmClient:
    def respond(request: LlmRequest) -> LlmResponse:
        n = len(request.messages)
        if n == 1:
            window = {"start": HOUR, "end": HOUR}
            return reply(
                "get_series", {"node": "payment_success_rate", "segment": SEGMENT, "window": window}, n, "Read."
            )
        result = json.loads(request.messages[-1]["content"][0]["content"])
        if "fact_handles" not in result:  # the answer was sent back: retry without digits
            return reply("answer", {"text": "PayCo payments failed.", "claims": []}, n)
        fact = result["fact_handles"][0]["id"]
        return reply("answer", {"text": answer_text, "claims": [{"fact_id": fact, "wording": "success rate"}]}, n)

    return FakeLlmClient(responder=respond)


@pytest.fixture(scope="module")
def source(s1_world: WorldPaths) -> LiveSource:
    src = LiveSource(s1_world.world, agent="off")
    for as_of in src.runtime.ticks():
        src.runtime.tick(as_of)
        if src.runtime.book.incidents:
            break
    return src


def client(source: LiveSource, fake: FakeLlmClient) -> TestClient:
    journal = Journal(stream=source.bus.stream)
    store = EvidenceStore()
    source.agent = AgentService(
        "live", journal, client=fake, store=store, asker=AskRunner(fake, journal, store, mode="replay")
    )
    return TestClient(create_app(source, start=False))


def test_off_agent_reports_why(source: LiveSource) -> None:
    with TestClient(create_app(source, start=False)) as c:
        health = c.get("/agent/health").json()
        assert health["enabled"] is False and "off" in health["reason"]
        assert c.get("/agent/activity").json()["records"] == []
        assert c.post("/agent/ask", json={"question": "why?"}).status_code == 409


def test_ask_answers_with_verified_claims(source: LiveSource) -> None:
    with client(source, asker("PayCo payments in Germany failed.")) as c:
        body = c.post("/agent/ask", json={"question": "What broke?"}).json()
        assert body["status"] == "answered"
        assert body["claims"] and body["receipt_links"]
        assert "[q" in body["answer"]  # the figure was rendered by the host with its receipt
        kinds = [r["kind"] for r in c.get("/agent/activity").json()["records"]]
        assert kinds[0] == "chat_question" and kinds[-1] == "chat_answer" and "tool_result" in kinds
        link = body["receipt_links"][0]
        receipt = c.get(f"/agent/receipts/{link['run_id']}/{link['world_revision']}/{link['receipt_id']}")
        assert receipt.status_code == 200 and receipt.json()["id"] == link["receipt_id"]
        runs = c.get("/agent/runs").json()
        assert runs[-1]["kind"] == "ask" and runs[-1]["llm_calls"] == 2


def test_digits_in_prose_are_sent_back(source: LiveSource) -> None:
    with client(source, asker("Success fell to 61%.")) as c:
        body = c.post("/agent/ask", json={"question": "How bad?"}).json()
        assert body["status"] == "answered" and "61" not in body["answer"]
