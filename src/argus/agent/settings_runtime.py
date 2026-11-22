"""Apply the operator's model and budget choices at live agent work boundaries."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from argus.agent import provider
from argus.agent.ask import AskRunner
from argus.agent.investigate import AgentSelector, Budget
from argus.agent.provider import (
    LOOP_MODEL,
    SYNTHESIS_MODEL,
    AnthropicClient,
    Cassette,
    ProviderUnavailable,
    RecordingClient,
    SpendLedger,
)
from argus.agent.service import AgentService
from argus.agent.types import AgentMode, LlmClient, LlmRequest, LlmResponse
from argus.evidence import EvidenceStore
from argus.settings import AiModel, Budgets, Settings, SettingsStore, provider_settings, write_private_json
from argus.skeptic.critic import CRITIC_MODEL


def default_settings() -> Settings:
    budget = Budget()
    return Settings(
        budgets=Budgets(**{key: getattr(budget, key) for key in Budgets.model_fields if key != "monthly_usd"})
    )


def run_budget(caps: Budgets, remaining: float | None = None) -> Budget:
    return Budget(
        requests=caps.requests,
        tool_calls=caps.tool_calls,
        input_tokens=caps.input_tokens,
        output_tokens=caps.output_tokens,
        usd=caps.usd if remaining is None else min(caps.usd, remaining),
        wall_seconds=caps.wall_seconds,
        tokens_per_call=max(1, min(Budget().tokens_per_call, caps.output_tokens)),
    )


class MonthlySpend:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.month = ""
        self.usd = 0.0
        if path is not None and path.exists():
            try:
                saved = json.loads(path.read_bytes())
                self.month, self.usd = str(saved["month"]), float(saved["usd"])
            except (ValueError, TypeError, KeyError, OSError):
                raise RuntimeError("The local monthly spend file is invalid.") from None

    def remaining(self, cap: float | None) -> float | None:
        if cap is None:
            return None
        with self.lock:
            self._rollover()
            return max(0.0, cap - self.usd)

    def charge(self, value: float) -> None:
        self._rollover()
        self.usd += value
        if self.path is not None:
            try:
                write_private_json(self.path, {"month": self.month, "usd": self.usd})
            except OSError:
                raise ProviderUnavailable("The local monthly spend file could not be updated.") from None

    def _rollover(self) -> None:
        now = datetime.now(UTC).strftime("%Y-%m")
        if now != self.month:
            self.month, self.usd = now, 0.0


@dataclass(frozen=True)
class Models:
    loop: str
    synthesis: str
    critic: str

    def public(self) -> dict[str, str]:
        return {"loop": self.loop, "synthesis": self.synthesis, "critic": self.critic}


class _ProviderFailure(ProviderUnavailable):
    def __init__(self, response: LlmResponse | None) -> None:
        super().__init__("The selected model provider could not complete the request.")
        self.response = response


class SettingsClient:
    """Meter every live call and keep configured credentials out of provider error text."""

    def __init__(self, inner: LlmClient, settings: SettingsStore, meter: MonthlySpend, models: Models) -> None:
        self.inner = inner
        self.settings = settings
        self.meter = meter
        self.models = models

    def create(self, request: LlmRequest) -> LlmResponse:
        chosen = self.models.critic if request.key.startswith("critic:") else request.model
        with self.meter.lock:
            remaining = self.meter.remaining(self.settings.read().budgets.monthly_usd)
            if remaining is not None and remaining <= 0:
                raise ProviderUnavailable("The monthly model budget has been reached.")
            if provider.price(chosen, {}) is None:
                raise ProviderUnavailable("The selected model has no configured pricing.")
            try:
                response = self.inner.create(request.model_copy(update={"model": chosen}))
            except Exception as exc:
                provider_response = getattr(exc, "response", None)
                billed = provider_response if isinstance(provider_response, LlmResponse) else None
                if billed is not None:
                    self._charge(billed)
                raise _ProviderFailure(billed) from None
            self._charge(response)
            return response

    def _charge(self, response: LlmResponse) -> None:
        charge = provider.price(response.model, response.usage)
        if charge is not None:
            self.meter.charge(charge)


class SettingsAgent:
    """Swap the provider between runs while keeping the stream's journal and recorded activity."""

    def __init__(self, initial: AgentService, mode: AgentMode, settings: SettingsStore) -> None:
        self.initial = initial
        self.mode = mode
        self.settings = settings
        self.current = initial
        self.chosen: AiModel | None = None
        self.lock = threading.Lock()
        self.spend = SpendLedger()
        self.meter = MonthlySpend(settings.path.with_name(".argus-monthly-spend.json") if settings.path else None)
        self.recording = initial.client.cassette if isinstance(initial.client, RecordingClient) else Cassette()

    def refresh(self) -> AgentService:
        with self.lock:
            config = self.settings.read().ai
            if self.chosen == config:
                return self.current
            self.current = self._configured()
            self.chosen = config
            return self.current

    def budget(self) -> Budget:
        caps = self.settings.read().budgets
        return run_budget(caps, self.meter.remaining(caps.monthly_usd))

    def health(self) -> dict[str, Any]:
        caps = self.settings.read().budgets
        return caps.model_dump()

    def _configured(self) -> AgentService:
        if self.mode == "off":
            self.initial.settings_caps = self.health
            return self.initial
        try:
            raw, models = self._client()
        except (ImportError, ProviderUnavailable, ValueError, OSError):
            return replace(
                self.initial,
                client=None,
                selector=None,
                asker=None,
                reason="The selected provider is unavailable. Check the provider and API key.",
                settings_caps=self.health,
            )
        client: LlmClient = SettingsClient(raw, self.settings, self.meter, models)
        if self.mode == "record":
            client = RecordingClient(client, self.recording)
        journal, profile = self.initial.journal, self.initial.profile
        store = self.initial.store or EvidenceStore()
        selector = AgentSelector(client, journal, self.mode, self.spend, self.budget(), models.loop, profile=profile)
        asker = AskRunner(client, journal, store, self.mode, self.spend, models.loop)
        return replace(
            self.initial,
            mode=self.mode,
            reason="",
            client=client,
            selector=selector,
            asker=asker,
            store=store,
            settings_caps=self.health,
            settings_models=models.public(),
        )

    def _client(self) -> tuple[LlmClient, Models]:
        if os.environ.get("ARGUS_DISABLE_PROVIDER") == "1":
            raise ProviderUnavailable("Live providers are disabled.")
        name, model, key = provider_settings(self.settings.read())
        initial_models = getattr(self.initial, "models", None)
        if name is None and self.initial.client is not None:
            client = self.initial.client
            if isinstance(client, RecordingClient):
                client = client.inner
            return client, Models(
                getattr(initial_models, "loop", LOOP_MODEL),
                getattr(initial_models, "synthesis", SYNTHESIS_MODEL),
                getattr(initial_models, "critic", CRITIC_MODEL),
            )
        name = name or os.environ.get("ARGUS_PROVIDER", "anthropic")
        if name == "openai":
            adapter = import_module("argus.agent.openai_provider")
            client = adapter.OpenAIClient(key=key)
            defaults = client.models(critic=self.initial.profile.on("critic"))
            return client, Models(model or defaults.loop, defaults.synthesis, defaults.critic)
        if name == "anthropic":
            return AnthropicClient(key), Models(model or LOOP_MODEL, SYNTHESIS_MODEL, CRITIC_MODEL)
        raise ProviderUnavailable("Select a known provider.")
