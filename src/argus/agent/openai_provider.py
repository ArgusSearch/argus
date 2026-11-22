"""OpenAI Responses adapter for Argus's tool loop."""

from __future__ import annotations

import json
import time
from contextlib import suppress
from typing import Any

import httpx2

from argus.agent.provider import (
    OPENAI_ASTRA,
    OPENAI_SOL,
    OPENAI_UNAVAILABLE,
    AgentModels,
    ProviderUnavailable,
    api_key,
)
from argus.agent.types import LlmRequest, LlmResponse

API = "https://api.openai.com/v1"
TOOL_ID_PREFIX = "toolu_openai_"


def _items(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        if isinstance(content, str):
            items.append({"role": role, "content": content})
            continue
        # Replay each native assistant item in order, including encrypted reasoning and message phase.
        native = next((block["openai_output"] for block in content if "openai_output" in block), None)
        if role == "assistant" and native is not None:
            items.extend(native)
            continue
        for block in content:
            kind = block["type"]
            if kind == "text":
                items.append({"role": role, "content": block["text"]})
            elif kind == "tool_result":
                tool_id = block["tool_use_id"]
                if tool_id.startswith(TOOL_ID_PREFIX):
                    tool_id = bytes.fromhex(tool_id.removeprefix(TOOL_ID_PREFIX)).decode()
                items.append({"type": "function_call_output", "call_id": tool_id, "output": block["content"]})
            elif kind == "tool_use":
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block["id"],
                        "name": block["name"],
                        "arguments": json.dumps(block["input"]),
                    }
                )
    return items


def _usage(data: dict[str, Any]) -> dict[str, int]:
    details = data.get("input_tokens_details") or {}
    read = details.get("cached_tokens") or 0
    written = details.get("cache_write_tokens") or 0
    return {
        "input_tokens": data["input_tokens"] - read - written,
        "output_tokens": data["output_tokens"],
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": written,
    }


class OpenAIClient:
    def __init__(
        self,
        key: str | None = None,
        timeout: float = 45.0,
        max_retries: int = 1,
        transport: httpx2.BaseTransport | None = None,
        *,
        base_url: str = API,
    ) -> None:
        key = key or api_key("OPENAI_API_KEY")
        if not key:
            raise ProviderUnavailable("OPENAI_API_KEY is not set")
        self._http = httpx2.Client(
            base_url=base_url, headers={"Authorization": f"Bearer {key}"}, timeout=timeout, transport=transport
        )
        self._max_retries = max(0, max_retries)

    def models(self, *, critic: bool) -> AgentModels:
        if critic:
            try:
                data, _ = self._request("GET", "/models")
                if not any(model["id"] == OPENAI_ASTRA for model in data["data"]):
                    return AgentModels.openai(critic=OPENAI_SOL)
            except (ProviderUnavailable, KeyError, TypeError):
                return AgentModels.openai(critic=OPENAI_SOL)
        return AgentModels.openai()

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[dict[str, Any], str | None]:
        for attempt in range(self._max_retries + 1):
            delay = min(0.5 * 2**attempt, 8)
            try:
                reply = self._http.request(method, path, json=body)
            except httpx2.TransportError:
                retryable = True
            else:
                try:
                    data = reply.json()
                except ValueError:
                    data = None
                if reply.is_success and isinstance(data, dict):
                    return data, reply.headers.get("x-request-id")
                retryable = reply.status_code in (408, 409, 429) or reply.status_code >= 500
                if isinstance(data, dict) and isinstance(data.get("error"), dict):
                    retryable = retryable and data["error"].get("code") != "insufficient_quota"
                with suppress(ValueError):
                    delay = min(max(0, float(reply.headers.get("retry-after", delay))), 8)
            if not retryable or attempt == self._max_retries:
                break
            time.sleep(delay)
        raise ProviderUnavailable(OPENAI_UNAVAILABLE)

    @staticmethod
    def request_body(request: LlmRequest) -> dict[str, Any]:
        return {
            "model": request.model,
            "instructions": request.system,
            "input": _items(request.messages),
            "tools": [
                {
                    "type": "function",
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                    "strict": False,
                }
                for tool in request.tools
            ],
            "parallel_tool_calls": bool(request.tools),
            "max_output_tokens": request.max_tokens,
            "reasoning": {"effort": "low"},
            "service_tier": "default",
            "store": False,
        }

    def create(self, request: LlmRequest) -> LlmResponse:
        try:
            data, request_id = self._request("POST", "/responses", self.request_body(request))
            response = LlmResponse(
                model=data["model"],
                content=[],
                stop_reason="end_turn",
                usage=_usage(data["usage"]) if data.get("usage") else {},
                request_id=request_id,
            )
        except (KeyError, TypeError, ValueError):
            raise ProviderUnavailable(OPENAI_UNAVAILABLE) from None

        try:
            return self._content(data, response)
        except (KeyError, TypeError, ValueError):
            response.content.clear()
            response.stop_reason = "unavailable"
            raise ProviderUnavailable(OPENAI_UNAVAILABLE, response if response.usage else None) from None

    @staticmethod
    def _content(data: dict[str, Any], response: LlmResponse) -> LlmResponse:
        status = data["status"]
        if status == "incomplete" and (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
            response.stop_reason = "max_tokens"
            return response

        output = data.get("output", [])
        if status != "completed" or any(
            block["type"] == "refusal" for item in output if item["type"] == "message" for block in item["content"]
        ):
            response.stop_reason = "refusal" if status == "completed" else "unavailable"
            raise ProviderUnavailable(OPENAI_UNAVAILABLE, response if response.usage else None)

        for item in output:
            if item["type"] == "message":
                response.content.extend(
                    {"type": "text", "text": block["text"]}
                    for block in item["content"]
                    if block["type"] == "output_text"
                )
            elif item["type"] == "function_call":
                args = json.loads(item["arguments"])
                if not isinstance(args, dict):
                    raise ValueError("tool arguments must be an object")
                response.content.append(
                    {
                        "type": "tool_use",
                        # Keep the live-to-recorded ID normalization used by request_sha.
                        "id": TOOL_ID_PREFIX + item["call_id"].encode().hex(),
                        "name": item["name"],
                        "input": args,
                    }
                )
                response.stop_reason = "tool_use"
        if output:
            # The live loop carries these into the next request. The cassette sanitizer drops them.
            response.content.append({"type": "redacted_thinking", "openai_output": output})
        return response
