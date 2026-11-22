"""Model access behind the frozen `LlmClient` protocol: live, recording, replaying; tariff and spend ledger.

The live factory selects Anthropic Messages or OpenAI Responses. Keys come from the environment or the
repository's git-ignored `.env`.
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

from argus.agent.journal import Journal
from argus.agent.types import LlmClient, LlmRequest, LlmResponse, UsageRecord
from argus.graph.store import REPO

LOOP_MODEL = os.environ.get("ARGUS_AGENT_MODEL", "claude-sonnet-5-5")
SYNTHESIS_MODEL = os.environ.get("ARGUS_AGENT_SYNTHESIS_MODEL", "claude-opus-5-5")
CRITIC_MODEL = os.environ.get("ARGUS_AGENT_CRITIC_MODEL", "claude-opus-5-5")
OPENAI_SOL = "gpt-6.2-sol"
OPENAI_ASTRA = "gpt-6.2-astra"
OPENAI_MODELS = (OPENAI_SOL, OPENAI_ASTRA)
OPENAI_UNAVAILABLE = "The OpenAI provider is unavailable"

TARIFF = "anthropic-2026-11"
OPENAI_TARIFF = "openai-2026-11"
# USD per million tokens: ordinary input, output, cache write, cache read.
# OpenAI Standard rates, 30-minute cache writes, checked 2026-11-22:
# https://developers.openai.com/api/docs/models/gpt-6.2-sol
# https://developers.openai.com/api/docs/models/gpt-6.2-astra
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    OPENAI_SOL: (2.0, 10.0, 2.50, 0.10),
    OPENAI_ASTRA: (8.0, 40.0, 10.0, 0.40),
}


@dataclass(frozen=True)
class AgentModels:
    provider: str = "anthropic"
    loop: str = LOOP_MODEL
    synthesis: str = SYNTHESIS_MODEL
    critic: str = CRITIC_MODEL

    @classmethod
    def openai(cls, critic: str = OPENAI_ASTRA) -> AgentModels:
        return cls(provider="openai", loop=OPENAI_SOL, synthesis=OPENAI_ASTRA, critic=critic)


ANTHROPIC_MODELS = AgentModels()


def price(model: str, usage: dict[str, int]) -> float | None:
    """USD of one call, or None for a model without a tariff (never guessed; trips the run budget)."""
    p = PRICES.get(model)
    if p is None:
        return None
    ordinary = usage.get("input_tokens", 0)
    written = usage.get("cache_creation_input_tokens", 0)
    cached = usage.get("cache_read_input_tokens", 0)
    output_cost = usage.get("output_tokens", 0) * p[1]
    if model in OPENAI_MODELS and ordinary + written + cached > 272_000:
        return (2 * (ordinary * p[0] + written * p[2] + cached * p[3]) + 1.5 * output_cost) / 1e6
    return (ordinary * p[0] + output_cost + written * p[2] + cached * p[3]) / 1e6


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
        tariff=OPENAI_TARIFF if response.model in OPENAI_MODELS else TARIFF,
        stop_reason=response.stop_reason,
        wall_ms=wall_ms,
    )


def api_key(name: str = "ANTHROPIC_API_KEY") -> str | None:
    """Read a provider key from the environment or the repository's git-ignored `.env`."""
    key = os.environ.get(name)
    if key:
        return key
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            assignment, _, value = line.partition("=")
            if assignment.strip().removeprefix("export ").strip() == name and value.strip():
                return value.strip().strip("'\"") or None
    return None


class ProviderUnavailable(RuntimeError):
    """No provider: no key, a refusal, or a replay without a matching recording."""

    def __init__(self, message: str, response: LlmResponse | None = None) -> None:
        super().__init__(message)
        self.response = response


def call_model(
    client: LlmClient, request: LlmRequest, journal: Journal, run_id: str, index: int
) -> tuple[LlmResponse, UsageRecord]:
    """Record metered calls, including provider refusals that report usage."""
    started = time.monotonic()

    def log(response: LlmResponse) -> UsageRecord:
        usage = usage_record(run_id, index, response, int((time.monotonic() - started) * 1000))
        journal.add_usage(usage)
        return usage

    try:
        response = client.create(request)
    except ProviderUnavailable as exc:
        if exc.response is not None:
            log(exc.response)
        raise
    return response, log(response)


def live_client(*, critic: bool = False) -> tuple[LlmClient, AgentModels]:
    """Resolve the requested live provider, preferring OpenAI when both keys are configured."""
    from argus.agent.openai_provider import OpenAIClient

    if os.environ.get("ARGUS_DISABLE_PROVIDER") == "1":
        raise ProviderUnavailable("live providers are disabled")
    provider = os.environ.get("ARGUS_PROVIDER", "").strip().lower()
    if provider not in ("", "openai", "anthropic"):
        raise ProviderUnavailable("ARGUS_PROVIDER must be openai or anthropic")
    if provider in ("", "openai") and (key := api_key("OPENAI_API_KEY")):
        client = OpenAIClient(key=key)
        return client, client.models(critic=critic)
    if provider in ("", "anthropic") and (key := api_key()):
        return AnthropicClient(key), ANTHROPIC_MODELS
    key_name = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(
        provider, "OPENAI_API_KEY or ANTHROPIC_API_KEY"
    )
    raise ProviderUnavailable(f"configure {key_name} for live agent access")


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
    def __init__(self, inner: LlmClient, cassette: Cassette | None = None) -> None:
        self.inner = inner
        self.cassette = cassette or Cassette()
        self._lock = threading.Lock()

    def create(self, request: LlmRequest) -> LlmResponse:
        try:
            response = self.inner.create(request)
        except ProviderUnavailable as exc:
            if request.model in OPENAI_MODELS:
                with self._lock:
                    self.cassette.lines.append(
                        {
                            "key": request.key,
                            "request_sha": request_sha(request),
                            "response": sanitized(exc.response, request.key) if exc.response else None,
                            "unavailable": True,
                        }
                    )
            raise
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
        if line.get("unavailable"):
            response = LlmResponse.model_validate(line["response"]) if line["response"] else None
            raise ProviderUnavailable(OPENAI_UNAVAILABLE, response)
        return LlmResponse.model_validate(line["response"])

    def unused(self) -> Iterable[str]:
        return [k for k, lines in self._by_key.items() for _ in lines]


# ---------------------------------------------------------------------------------------------- spend


class SpendLedger:
    """Appends one line per model and run to the JSONL ledger named by `ARGUS_SPEND_LEDGER`:
    Includes the provider, model, cost, token counts and run. Replays write nothing."""

    def __init__(self, path: Path | None = None, *, persist: bool = True, durable: bool = False) -> None:
        env = os.environ.get("ARGUS_SPEND_LEDGER") if persist else None
        self.path = path if path is not None else (Path(env).expanduser() if env else None)
        self._lock = threading.Lock()
        self._durable = durable

    def append_run(self, run_id: str, purpose: str, usage: list[UsageRecord]) -> list[dict[str, Any]]:
        lines: dict[str, dict[str, Any]] = {}
        for u in usage:
            line = lines.setdefault(
                u.model,
                {
                    "provider": "openai" if u.tariff == OPENAI_TARIFF else "anthropic",
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
                if self._durable:
                    f.flush()
                    os.fsync(f.fileno())
        return list(lines.values())
