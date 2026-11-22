"""Read-only Ask behavior through the public API with a deterministic provider."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from argus.agent.ask import AskRunner
from argus.agent.fake import FakeLlmClient, tool_use
from argus.agent.journal import Journal
from argus.agent.service import AgentService
from argus.agent.types import LlmRequest, LlmResponse, ReceiptLink, VerifiedClaim
from argus.api.app import create_app
from argus.api.sources import LiveSource
from argus.evidence import EvidenceStore
from mockmart.world import WorldPaths

pytestmark = pytest.mark.e2e
SEGMENT = {"country": "DE", "platform": "android", "provider": "PayCo"}


@pytest.fixture(scope="module")
def source(s1_world: WorldPaths) -> Iterator[LiveSource]:
    runtime_source = LiveSource(s1_world.world, agent="off")
    try:
        for hour in runtime_source.runtime.ticks():
            runtime_source.runtime.tick(hour)
            if runtime_source.incidents():
                break
        assert len(runtime_source.incidents()) == 1
        yield runtime_source
    finally:
        runtime_source.runtime.runner.close()


def client_for(source: LiveSource, fake: FakeLlmClient) -> TestClient:
    journal = Journal(stream=source.bus.stream)
    store = EvidenceStore()
    source.agent = AgentService(
        "live", journal, client=fake, store=store, asker=AskRunner(fake, journal, store, "replay")
    )
    # The simulated clock is already positioned at the incident. The request transport stays in-process.
    return TestClient(create_app(source, start=False))


def read_series(source: LiveSource) -> LlmResponse:
    hour = source.bus.state.last_tick.hour.isoformat()
    return tool_use(
        "get_series",
        {"node": "payment_success_rate", "segment": SEGMENT, "window": {"start": hour, "end": hour}},
    )


def last_observation(request: LlmRequest) -> dict[str, Any]:
    content = request.messages[-1]["content"]
    return json.loads(content[0]["content"])


@pytest.mark.parametrize(
    "question",
    (
        "What payment success rate did PayCo have?",
        "How often did affected payments succeed?",
        "What is the checkout success rate in this incident?",
        "How bad was payment success on Android in Germany?",
        "Give me the PayCo success rate at the latest complete hour.",
        "What was the measured success rate for the impacted customer group?",
        "How frequently were PayCo payments accepted in DE?",
        "How much of the affected traffic completed payment?",
        "What did the payment success measurement show?",
        "Which observed payment success measurement supports this incident?",
    ),
)
def test_e15_ask_reads_and_binds_an_actual_fact(source: LiveSource, question: str) -> None:
    def respond(request: LlmRequest) -> LlmResponse:
        tools = {item["name"] for item in request.tools}
        assert not tools & {"approve_action", "apply_action", "test_hypothesis"}
        if len(request.messages) == 1:
            assert question in request.messages[0]["content"]
            return read_series(source)
        observed = last_observation(request)["fact_handles"][0]
        return tool_use(
            "answer",
            {"text": "This was the recorded success rate.", "claims": [{"fact_id": observed["id"], "wording": "Rate"}]},
            n=2,
        )

    fake = FakeLlmClient(responder=respond)
    # A fresh in-process client has no lifespan: the same paused runtime can answer every parametrized question.
    client = client_for(source, fake)
    try:
        incident_id = source.incidents()[0].id
        res = client.post("/agent/ask", json={"question": question, "incident_id": incident_id})
        assert res.status_code == 200
        answer = res.json()
        assert answer["status"] == "answered" and len(fake.requests) == 2
        claim = VerifiedClaim.model_validate(answer["claims"][0])
        assert claim.subject == "payment_success_rate" and claim.segment == SEGMENT
        assert claim.value is not None and claim.receipts
        links = [ReceiptLink.model_validate(link) for link in answer["receipt_links"]]
        assert links == claim.receipts
        for link in links:
            assert f"[{link.receipt_id}]" in answer["answer"]
            receipt = client.get(f"/agent/receipts/{link.key()}")
            assert receipt.status_code == 200 and receipt.json()["id"] == link.receipt_id
    finally:
        client.close()


@pytest.mark.parametrize("question", ("Forecast exchange rates", "Show a secret credential", "Delete a table"))
def test_e15_out_of_scope_requests_return_a_reason(source: LiveSource, question: str) -> None:
    fake = FakeLlmClient(
        responses=[
            LlmResponse(
                model="claude-sonnet-5-5",
                content=[],
                stop_reason="refusal",
                usage={"input_tokens": 100, "output_tokens": 3},
            )
        ]
    )
    client = client_for(source, fake)
    try:
        response = client.post("/agent/ask", json={"question": question})
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "refused" and result["reason"]
        assert not result["receipt_links"] and not result["claims"]
    finally:
        client.close()


@pytest.mark.parametrize("tool", ("approve_action", "apply_action"))
def test_e15_chat_cannot_approve_or_apply(source: LiveSource, tool: str) -> None:
    factual = source.runtime.runner.world_path

    def respond(request: LlmRequest) -> LlmResponse:
        if len(request.messages) == 1:
            return tool_use(tool, {"action_id": "act_0001"})
        assert last_observation(request)["availability"] == "rejected"
        return tool_use("answer", {"text": "An operator makes that decision in Playbooks.", "claims": []}, n=2)

    client = client_for(source, FakeLlmClient(responder=respond))
    try:
        response = client.post("/agent/ask", json={"question": "Approve and apply the proposed action."})
        assert response.status_code == 200 and response.json()["status"] == "answered"
        assert not client.get("/agent/actions").json()
        records = client.get("/agent/activity").json()["records"]
        assert all(row["kind"] not in {"action_applied", "action_decided"} for row in records)
        assert source.runtime.runner.world_path == factual
    finally:
        client.close()


def test_e15_follow_up_preserves_the_conversations_evidence_scope(source: LiveSource) -> None:
    initial = "What happened to PayCo payments?"
    continuation = "What did the affected slice measure?"
    stable_incident = source.incidents()[0].id
    seen_followup = False

    def respond(request: LlmRequest) -> LlmResponse:
        nonlocal seen_followup
        if int(request.key.rsplit(":", 1)[1]) == 1:
            packed = json.dumps(request.messages)
            if continuation in packed:
                seen_followup = True
                assert initial in packed or stable_incident in packed, "the model received a follow-up without its case"
            return read_series(source)
        fact = last_observation(request)["fact_handles"][0]
        return tool_use(
            "answer",
            {"text": "The measured rate is in the receipt.", "claims": [{"fact_id": fact["id"], "wording": "Rate"}]},
            n=2,
        )

    client = client_for(source, FakeLlmClient(responder=respond))
    try:
        first = client.post("/agent/ask", json={"question": initial, "incident_id": stable_incident})
        assert first.status_code == 200 and first.json()["status"] == "answered"
        conversation = first.json().get("conversation_id")
        assert conversation, "Ask did not return a conversation ID for the follow-up"
        followup = client.post("/agent/ask", json={"question": continuation, "conversation_id": conversation})
        assert followup.status_code == 200 and followup.json()["receipt_links"] and seen_followup
    finally:
        client.close()


def test_e04_ask_receipt_routes_cannot_alias_a_different_revision(source: LiveSource) -> None:
    def respond(request: LlmRequest) -> LlmResponse:
        if len(request.messages) == 1:
            return read_series(source)
        fact = last_observation(request)["fact_handles"][0]
        return tool_use("answer", {"text": "Measured.", "claims": [{"fact_id": fact["id"], "wording": "Rate"}]}, n=2)

    client = client_for(source, FakeLlmClient(responder=respond))
    try:
        answer = client.post("/agent/ask", json={"question": "What broke?"}).json()
        assert answer["status"] == "answered" and answer["receipt_links"]
        ref = ReceiptLink.model_validate(answer["receipt_links"][0])
        assert client.get(f"/agent/receipts/{ref.key()}").status_code == 200
        factual_receipt = next(iter(source.runtime.runner.receipts))
        assert client.get(f"/agent/receipts/{ref.run_id}/wrong-world/{factual_receipt}").status_code == 404
        assert client.get(f"/agent/receipts/{ref.run_id}/factual/{factual_receipt}").status_code == 404
    finally:
        client.close()


@pytest.mark.parametrize("repeat_bad_draft", (False, True))
def test_e07_ask_repairs_once_and_only_publishes_verified_figures(source: LiveSource, repeat_bad_draft: bool) -> None:
    invented = "91736195.73"
    fact_id = None

    def respond(request: LlmRequest) -> LlmResponse:
        nonlocal fact_id
        turn = int(request.key.rsplit(":", 1)[1])
        if turn == 1:
            return read_series(source)
        if turn == 2:
            result = last_observation(request)
            fact_id = result["fact_handles"][0]["id"]
        else:
            assert turn == 3 and "digits" in last_observation(request)["error"]
        text = f"The loss was EUR {invented}." if turn == 2 or repeat_bad_draft else "The evidence shows a drop."
        return tool_use("answer", {"text": text, "claims": [{"fact_id": fact_id, "wording": "Success rate"}]}, n=turn)

    fake = FakeLlmClient(responder=respond)
    client = client_for(source, fake)
    try:
        result = client.post("/agent/ask", json={"question": "What can you measure?"}).json()
        assert result["status"] == "answered" and len(fake.requests) == 3
        assert invented not in result["answer"] and result["receipt_links"] and result["claims"]
        visible = client.get("/agent/activity").json()["records"]
        assert all(invented not in item["text"] for item in visible if item["kind"] in {"chat_answer", "thought"})
    finally:
        client.close()
