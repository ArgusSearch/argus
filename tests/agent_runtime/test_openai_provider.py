"""Exercise the Responses adapter against an in-process HTTP transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from argus.agent.journal import Journal
from argus.agent.openai_provider import OpenAIClient
from argus.agent.profile import V1, Profile
from argus.agent.provider import (
    OPENAI_ASTRA,
    OPENAI_SOL,
    OPENAI_TARIFF,
    OPENAI_UNAVAILABLE,
    ProviderUnavailable,
    RecordingClient,
    ReplayClient,
    SpendLedger,
    call_model,
    price,
)
from argus.agent.service import build
from argus.agent.types import LlmRequest

TEST_KEY = "test-openai-credential"
USAGE = {
    "input_tokens": 1000,
    "input_tokens_details": {"cached_tokens": 300, "cache_write_tokens": 500},
    "output_tokens": 50,
    "output_tokens_details": {"reasoning_tokens": 25},
}
REQUEST = LlmRequest(
    model=OPENAI_SOL,
    system="Choose checks.",
    messages=[{"role": "user", "content": "Check the data."}],
    tools=[
        {
            "name": "check",
            "description": "Check a dimension",
            "input_schema": {"type": "object", "properties": {"scope": {"type": "string"}}},
        }
    ],
    max_tokens=1000,
    key="investigate:an_0001:1",
)


def client(handler: Callable[[httpx2.Request], httpx2.Response], **kwargs: Any) -> OpenAIClient:
    return OpenAIClient(key=TEST_KEY, transport=httpx2.MockTransport(handler), **kwargs)


def output(*items: dict[str, Any], status: str = "completed", **fields: Any) -> httpx2.Response:
    return httpx2.Response(
        200,
        headers={"x-request-id": "request-1"},
        json={"model": OPENAI_SOL, "status": status, "output": items, "usage": USAGE, **fields},
    )


def test_parallel_calls_round_trip_and_recording() -> None:
    reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque", "summary": []}
    commentary = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "phase": "commentary",
        "status": "completed",
        "content": [{"type": "output_text", "text": "I'll check both.", "annotations": []}],
    }
    calls = [
        {
            "type": "function_call",
            "id": f"fc_{i}",
            "call_id": f"call-{i}",
            "name": "check",
            "arguments": json.dumps({"scope": scope}),
            "status": "completed",
        }
        for i, scope in enumerate(("DE", "FR"))
    ]
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/responses"
        assert request.headers["Authorization"] == f"Bearer {TEST_KEY}"
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return output(reasoning, commentary, *calls)
        return output()

    recorder = RecordingClient(client(handler))
    first = recorder.create(REQUEST)
    assert first.stop_reason == "tool_use"
    assert [block["type"] for block in first.content] == ["text", "tool_use", "tool_use", "redacted_thinking"]
    assert first.content[0]["text"] == "I'll check both."
    assert [block["input"] for block in first.content[1:3]] == [{"scope": "DE"}, {"scope": "FR"}]
    assert first.request_id == "request-1"
    assert requests[0]["instructions"] == REQUEST.system
    assert requests[0]["input"] == REQUEST.messages
    assert requests[0]["max_output_tokens"] == REQUEST.max_tokens
    assert requests[0]["store"] is False and requests[0]["parallel_tool_calls"]
    assert requests[0]["tools"] == [
        {
            "type": "function",
            "name": "check",
            "description": "Check a dimension",
            "parameters": REQUEST.tools[0]["input_schema"],
            "strict": False,
        }
    ]

    def next_turn(content: list[dict[str, Any]]) -> LlmRequest:
        results = [
            {"type": "tool_result", "tool_use_id": block["id"], "content": result, "is_error": i == 1}
            for i, (block, result) in enumerate(zip(content[1:3], ('{"ok":true}', '{"error":"missing"}'), strict=True))
        ]
        return REQUEST.model_copy(
            update={
                "key": "investigate:an_0001:2",
                "messages": [
                    *REQUEST.messages,
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": results},
                ],
            }
        )

    assert recorder.create(next_turn(first.content)).stop_reason == "end_turn"
    assert requests[1]["input"] == [
        *REQUEST.messages,
        reasoning,
        commentary,
        *calls,
        {"type": "function_call_output", "call_id": "call-0", "output": '{"ok":true}'},
        {"type": "function_call_output", "call_id": "call-1", "output": '{"error":"missing"}'},
    ]
    stored = json.dumps(recorder.cassette.lines)
    assert all(value not in stored for value in ("opaque", "request-1", TEST_KEY))
    replay = ReplayClient(recorder.cassette)
    assert replay.create(next_turn(replay.create(REQUEST).content)).stop_reason == "end_turn"
    assert not list(replay.unused())


@pytest.mark.parametrize(
    ("status", "code", "count"),
    [
        (401, "invalid_api_key", 1),
        (500, "server_error", 2),
        (429, "rate_limit_exceeded", 2),
        (429, "insufficient_quota", 1),
    ],
)
def test_errors_are_neutral_and_retry_only_when_transient(status: int, code: str, count: int) -> None:
    calls = 0

    def handler(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            status, json={"error": {"code": code, "message": TEST_KEY}}, headers={"Retry-After": "0"}
        )

    with pytest.raises(ProviderUnavailable) as failure:
        client(handler).create(REQUEST)
    assert str(failure.value) == OPENAI_UNAVAILABLE
    assert failure.value.response is None
    assert calls == count


def test_retry_can_recover(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx2.ReadTimeout(TEST_KEY, request=request)
        if calls == 2:
            return httpx2.Response(429, headers={"Retry-After": "2"})
        return output()

    monkeypatch.setattr("argus.agent.openai_provider.time.sleep", sleeps.append)
    assert client(handler, max_retries=2).create(REQUEST).stop_reason == "end_turn"
    assert calls == 3
    assert sleeps == [0.5, 2]


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_billed_refusal_or_failure_is_safe_to_record_and_replay(status: str, tmp_path: Path) -> None:
    refusal = {"type": "message", "content": [{"type": "refusal", "refusal": TEST_KEY}]}
    recorder = RecordingClient(client(lambda _: output(refusal, status=status, error={"message": TEST_KEY})))
    journal = Journal()
    with pytest.raises(ProviderUnavailable, match=f"^{OPENAI_UNAVAILABLE}$"):
        call_model(recorder, REQUEST, journal, "run", 1)
    (usage,) = journal.usage
    assert usage.stop_reason == ("refusal" if status == "completed" else "unavailable")
    assert usage.tariff == OPENAI_TARIFF
    assert usage.request_id == "request-1"
    assert (usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens, usage.output_tokens) == (
        200,
        300,
        500,
        50,
    )
    assert usage.usd == pytest.approx(0.00218)
    assert price(
        OPENAI_ASTRA,
        {
            "input_tokens": 200,
            "cache_read_input_tokens": 300,
            "cache_creation_input_tokens": 500,
            "output_tokens": 50,
        },
    ) == pytest.approx(0.00872)
    assert price(OPENAI_SOL, {"input_tokens": 273_000, "output_tokens": 1000}) == pytest.approx(1.107)
    path = tmp_path / "spend.jsonl"
    (line,) = SpendLedger(path).append_run("run", "investigate", journal.usage)
    assert line == json.loads(path.read_text())
    assert (line["provider"], line["model"], line["usd"]) == ("openai", OPENAI_SOL, 0.00218)
    assert TEST_KEY not in json.dumps(recorder.cassette.lines)
    with pytest.raises(ProviderUnavailable, match=f"^{OPENAI_UNAVAILABLE}$") as replay:
        ReplayClient(recorder.cassette).create(REQUEST)
    assert replay.value.response is not None and replay.value.response.usage["output_tokens"] == 50


def test_output_token_limit_drops_partial_tool_calls() -> None:
    partial = {"type": "function_call", "call_id": "call-1", "name": "check", "arguments": "{"}
    response = client(
        lambda _: output(partial, status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    ).create(REQUEST)
    assert response.stop_reason == "max_tokens" and not response.content
    assert response.usage["output_tokens"] == 50


def test_live_provider_selection_and_critic_availability(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("argus.agent.provider.REPO", tmp_path)
    for variable in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ARGUS_PROVIDER", "ARGUS_DISABLE_PROVIDER"):
        monkeypatch.delenv(variable, raising=False)
    assert "OPENAI_API_KEY or ANTHROPIC_API_KEY" in build("live").reason
    monkeypatch.setenv("ARGUS_PROVIDER", "invalid")
    assert "ARGUS_PROVIDER" in build("live").reason
    monkeypatch.delenv("ARGUS_PROVIDER")
    (tmp_path / ".env").write_text("export OPENAI_API_KEY='openai-dotenv'\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-env")
    monkeypatch.setattr("argus.agent.provider.AnthropicClient", lambda key: key)
    available = [OPENAI_SOL, OPENAI_ASTRA]
    calls = []

    def models(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/models"
        return httpx2.Response(200, json={"data": [{"id": model} for model in available]})

    def openai(key: str) -> OpenAIClient:
        calls.append(key)
        return client(models)

    monkeypatch.setattr("argus.agent.openai_provider.OpenAIClient", openai)
    assert build("live", profile=V1).health()["models"]["loop"] == OPENAI_SOL
    assert calls == ["openai-dotenv"]
    monkeypatch.setenv("OPENAI_API_KEY", TEST_KEY)
    critic = Profile.of("v2", ["critic"])
    live = build("live", profile=critic)
    assert live.asker is not None and live.asker.model == OPENAI_SOL
    assert live.health()["models"]["critic"] == OPENAI_ASTRA
    assert calls[-1] == TEST_KEY
    available.remove(OPENAI_ASTRA)
    assert build("live", profile=critic).health()["models"]["critic"] == OPENAI_SOL
    monkeypatch.setenv("ARGUS_PROVIDER", "anthropic")
    assert build("record").models.provider == "anthropic"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    disabled = build("live")
    assert not disabled.enabled and "ANTHROPIC_API_KEY" in disabled.reason
