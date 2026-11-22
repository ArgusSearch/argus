"""Model access behind the frozen `LlmClient` protocol: live, recording, replaying; tariff and spend ledger.

`AnthropicClient` is the only code that opens a network connection. It reads `ANTHROPIC_API_KEY` from the
environment (or the repository's git-ignored `.env`) and never logs it.
`RecordingClient` wraps a client and keeps a cassette; `ReplayClient` answers from a cassette and never
constructs a provider, so a replay works with no key and no network.

Cassette line: `{"key", "request_sha", "response"}`. `key` is `<kind>:<subject>:<round>`; `request_sha` is
the SHA-256 of the canonical request (model, system, tools, messages with tool-use ids normalised).
A strict replay requires both to match (CI, evals); a lenient one matches by key and reports drift.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from argus.agent.types import LlmRequest, LlmResponse, UsageRecord
from argus.graph.store import REPO

LOOP_MODEL = os.environ.get("ARGUS_AGENT_MODEL", "claude-sonnet-5-5")
SYNTHESIS_MODEL = os.environ.get("ARGUS_AGENT_SYNTHESIS_MODEL", "claude-opus-5-5")

TARIFF = "anthropic-2026-11"
# USD per million tokens: input, output, cache write (5 min), cache read
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}


def price(model: str, usage: dict[str, int]) -> float | None:
    """USD of one call, or None for a model without a tariff (never guessed; trips the run budget)."""
    p = PRICES.get(model)
    if p is None:
        return None
    return (
        usage.get("input_tokens", 0) * p[0]
        + usage.get("output_tokens", 0) * p[1]
        + usage.get("cache_creation_input_tokens", 0) * p[2]
        + usage.get("cache_read_input_tokens", 0) * p[3]
    ) / 1e6


def usage_record(run_id: str, call_index: int, response: LlmResponse, wall_ms: int) -> UsageRecord:
    u = response.usage
    return UsageRecord(
        run_id=run_id,
        call_index=call_index,
        model=response.model,
        request_id=response.request_id,
        input_tokens=u.get("input_tokens", 0),
        output_tokens=u.get("output_tokens", 0),
        cache_read_tokens=u.get("cache_read_input_tokens", 0),
        cache_write_tokens=u.get("cache_creation_input_tokens", 0),
        usd=price(response.model, u),
        tariff=TARIFF,
        stop_reason=response.stop_reason,
        wall_ms=wall_ms,
    )


def api_key() -> str | None:
    """`ANTHROPIC_API_KEY` from the environment, else from the repository's git-ignored `.env`."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
                return value.strip().strip("'\"")
    return None


class ProviderUnavailable(RuntimeError):
    """No provider: no key, a refusal, or a replay without a matching recording."""


class AnthropicClient:
    """Live Messages API calls. Loop model: thinking off between tool calls, so the visible sentence before a
    tool call comes back as text. Synthesis model (thinking always on): a summary of its reasoning."""

    def __init__(self, key: str | None = None, timeout: float = 90.0, max_retries: int = 1) -> None:
        key = key or api_key()
        if not key:
            raise ProviderUnavailable("ANTHROPIC_API_KEY is not set")
        import anthropic

        self._client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=max_retries)

    def create(self, request: LlmRequest) -> LlmResponse:
        tools = [dict(t) for t in request.tools]
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "messages": request.messages,
            "tools": tools,
            "output_config": {"effort": "medium"},
        }
        if tools:
            kwargs["tool_choice"] = {"type": "auto"}
        if request.model.startswith("claude-opus"):
            kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        else:
            kwargs["thinking"] = {"type": "between_tools"}
        response = self._client.messages.create(**kwargs)
        u = response.usage
        usage = {
            "input_tokens": u.input_tokens or 0,
            "output_tokens": u.output_tokens or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None) or 0,
        }
        return LlmResponse(
            model=response.model,
            content=[block.model_dump(mode="json", exclude_none=True) for block in response.content],
            stop_reason=response.stop_reason or "end_turn",
            usage=usage,
            request_id=getattr(response, "_request_id", None),
        )


# ---------------------------------------------------------------------------------------------- cassettes

_TOOL_ID = re.compile(r"toolu_[A-Za-z0-9_]+")


def _public(content: Any) -> Any:
    """Content without private reasoning (thinking blocks), as recordings keep it."""
    if isinstance(content, list):
        return [
            _public(c)
            for c in content
            if not (isinstance(c, dict) and c.get("type") in ("thinking", "redacted_thinking"))
        ]
    if isinstance(content, dict):
        return {k: _public(v) for k, v in content.items()}
    return content


def request_sha(request: LlmRequest) -> str:
    """Hash of the request as a recording sees it: tool-use ids normalised, thinking blocks left out."""
    body = json.dumps(
        {
            "model": request.model,
            "system": request.system,
            "tools": request.tools,
            "messages": _public(request.messages),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(_TOOL_ID.sub("toolu_x", body).encode()).hexdigest()


@dataclass
class Cassette:
    lines: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> Cassette:
        return cls([json.loads(line) for line in path.read_text().splitlines() if line.strip()])

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line, sort_keys=True) + "\n" for line in self.lines))


def sanitized(response: LlmResponse, key: str) -> dict[str, Any]:
    """The response as a recording keeps it: no provider request id, no private reasoning, deterministic
    tool-use ids. A replay passes these ids back; `request_sha` normalises ids, so it still matches."""
    content = []
    n = 0
    for block in _public(response.content):
        if block.get("type") == "tool_use":
            n += 1
            block = {**block, "id": f"toolu_{re.sub(r'[^A-Za-z0-9]', '_', key)}_{n}"}
        content.append(block)
    data = response.model_copy(update={"content": content, "request_id": None}).model_dump(mode="json")
    return dict(data)


class RecordingClient:
    def __init__(self, inner: Any, cassette: Cassette | None = None) -> None:
        self.inner = inner
        self.cassette = cassette or Cassette()
        self._lock = threading.Lock()

    def create(self, request: LlmRequest) -> LlmResponse:
        response: LlmResponse = self.inner.create(request)
        with self._lock:
            self.cassette.lines.append(
                {"key": request.key, "request_sha": request_sha(request), "response": sanitized(response, request.key)}
            )
        return response


class CassetteMismatch(ProviderUnavailable):
    pass


class ReplayClient:
    """Answers from a cassette. Strict: key and request hash must match the next unused line with that key."""

    def __init__(self, cassette: Cassette, strict: bool = True) -> None:
        self.strict = strict
        self._by_key: dict[str, list[dict[str, Any]]] = {}
        for line in cassette.lines:
            self._by_key.setdefault(line["key"], []).append(line)
        self.drift: list[str] = []
        self._lock = threading.Lock()

    def create(self, request: LlmRequest) -> LlmResponse:
        with self._lock:
            pending = self._by_key.get(request.key)
            if not pending:
                raise CassetteMismatch(f"no recorded response for {request.key}")
            line = pending.pop(0)
        if line["request_sha"] != request_sha(request):
            if self.strict:
                raise CassetteMismatch(f"request for {request.key} differs from the recording")
            self.drift.append(request.key)
        return LlmResponse.model_validate(line["response"])

    def unused(self) -> Iterable[str]:
        return [k for k, lines in self._by_key.items() for _ in lines]


# ---------------------------------------------------------------------------------------------- spend


class SpendLedger:
    """Appends one line per model and run to the JSONL ledger named by `ARGUS_SPEND_LEDGER`:
    {"provider": "anthropic", "model": ..., "usd": ...} plus token counts and the run. Replays write nothing."""

    def __init__(self, path: Path | None = None) -> None:
        env = os.environ.get("ARGUS_SPEND_LEDGER")
        self.path = path if path is not None else (Path(env).expanduser() if env else None)
        self._lock = threading.Lock()

    def append_run(self, run_id: str, purpose: str, usage: list[UsageRecord]) -> list[dict[str, Any]]:
        lines: dict[str, dict[str, Any]] = {}
        for u in usage:
            line = lines.setdefault(
                u.model,
                {
                    "provider": "anthropic",
                    "model": u.model,
                    "usd": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "task": "argus-agent",
                    "purpose": f"{purpose}:{run_id}",
                    "ts": int(time.time()),
                },
            )
            line["usd"] = round(line["usd"] + (u.usd or 0.0), 6)
            line["input_tokens"] += u.input_tokens
            line["output_tokens"] += u.output_tokens
            line["cache_read_tokens"] += u.cache_read_tokens
            line["cache_write_tokens"] += u.cache_write_tokens
        if self.path is not None and lines:
            with self._lock, self.path.open("a") as f:
                for line in lines.values():
                    f.write(json.dumps(line) + "\n")
        return list(lines.values())
