"""The agent inside the API process: one journal, the pre-verdict selector for the runtime, Ask, and health.

`build(mode)` is called by `LiveSource`. Live and record modes need a provider key. Without one, or with
mode `off`, the runtime runs Stage 2 alone and `/agent/health` says why. Replay mode is served by the demo
playback (lane F); this service then only reports itself as off for live work. The agent profile (`v1`, or
`v2` with its features) comes from `ARGUS_AGENT_PROFILE` and `ARGUS_AGENT_FEATURES` (`argus.agent.profile`).
"""

from __future__ import annotations

import os
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from argus.agent.ask import AskResult, AskRunner, AskScope
from argus.agent.investigate import AgentSelector, Budget
from argus.agent.journal import Journal
from argus.agent.profile import V1, Profile
from argus.agent.provider import (
    ANTHROPIC_MODELS,
    AgentModels,
    Cassette,
    ProviderUnavailable,
    RecordingClient,
    SpendLedger,
    live_client,
)
from argus.agent.types import BOARD_VERSION, INTERFACE_VERSION, AgentMode, LlmClient
from argus.evidence import EvidenceStore
from argus.skeptic.critic import CriticBudget

MODES: tuple[AgentMode, ...] = ("live", "record", "off")


def configured_mode(flag: str | None = None) -> AgentMode:
    value = (flag or os.environ.get("ARGUS_AGENT") or "off").lower()
    if value not in MODES:
        raise ValueError(f"agent mode must be one of {MODES}, got {value!r}")
    return value


@dataclass
class AgentService:
    mode: AgentMode
    journal: Journal
    reason: str = ""
    client: LlmClient | None = None
    selector: AgentSelector | None = None
    store: EvidenceStore | None = None
    asker: AskRunner | None = None
    recording: Path | None = None
    settings_caps: Callable[[], dict[str, Any]] | None = field(default=None, kw_only=True)
    settings_models: dict[str, str] | None = field(default=None, kw_only=True)
    conversations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ask_owners: dict[str, str] = field(default_factory=dict)
    conversation_owners: dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    profile: Profile = V1
    models: AgentModels = ANTHROPIC_MODELS

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def health(self) -> dict[str, Any]:
        runs = list(self.journal.runs.values())
        budget = Budget()
        health: dict[str, Any] = {
            "enabled": self.enabled,
            "mode": self.mode,
            "reason": self.reason,
            "interface_version": INTERFACE_VERSION,
            "models": {"loop": self.models.loop, "synthesis": self.models.synthesis},
            "caps": {
                "requests": budget.requests,
                "tool_calls": budget.tool_calls,
                "input_tokens": budget.input_tokens,
                "output_tokens": budget.output_tokens,
                "usd": budget.usd,
                "wall_seconds": budget.wall_seconds,
            },
            "runs": len(runs),
            "usd": round(sum(r.usd for r in runs), 6),
            "profile": self.profile.name,
            "features": sorted(self.profile.features),
            "board_version": BOARD_VERSION,
        }
        if self.profile.on("critic"):
            critic = CriticBudget()
            health["models"]["critic"] = self.models.critic
            health["caps"]["critic"] = {
                "requests": critic.requests,
                "tool_calls": critic.tool_calls,
                "usd": critic.usd,
                "wall_seconds": critic.wall_seconds,
            }
        if self.settings_caps is not None:
            health["caps"].update(self.settings_caps())
        if self.settings_models is not None:
            health["models"].update(
                {key: self.settings_models[key] for key in health["models"] if key in self.settings_models}
            )
        return health

    def ask(
        self,
        question: str,
        scope: AskScope,
        incident_id: str | None,
        conversation_id: str | None = None,
        *,
        owner: str | None = None,
    ) -> AskResult:
        """A question, optionally following up an earlier one: the conversation keeps its incident scope and
        hands the earlier questions and answers to the model as context (never as evidence: every figure
        is verified again in the new run)."""
        if self.asker is None:
            raise ProviderUnavailable(self.reason or "the agent is off")
        with self.lock:  # one question at a time keeps cost and the activity log readable
            if conversation_id is not None and (
                conversation_id not in self.conversations or self.conversation_owners.get(conversation_id) != owner
            ):
                return AskResult(status="unknown_conversation", run_id="", reason=f"no conversation {conversation_id}")
            if conversation_id is None:
                conversation_id = secrets.token_urlsafe(18) if owner else f"conv_{len(self.conversations) + 1:04d}"
                if owner:
                    self.conversation_owners[conversation_id] = owner
            turns = self.conversations.setdefault(conversation_id, [])
            incident_id = incident_id or next((t["incident_id"] for t in turns if t["incident_id"]), None)
            if owner:
                result = self.asker.ask(
                    question,
                    scope,
                    incident_id,
                    history=turns,
                    on_start=lambda run_id: self.ask_owners.__setitem__(run_id, owner),
                )
            else:
                result = self.asker.ask(question, scope, incident_id, history=turns)
            result.conversation_id = conversation_id
            turns.append({"question": question, "answer": result.answer, "incident_id": incident_id})
        self.save()
        return result

    def save(self) -> None:
        """Record mode: write the cassette after every run so a crash keeps what was paid for."""
        if self.recording is not None and isinstance(self.client, RecordingClient):
            self.client.cassette.write(self.recording / "turns.jsonl")


def build(
    mode: AgentMode,
    stream: str = "local",
    recording: Path | None = None,
    profile: Profile | None = None,
    *,
    provider: Callable[[], tuple[LlmClient, AgentModels]] | None = None,
    spend: SpendLedger | None = None,
) -> AgentService:
    journal = Journal(stream=stream)
    profile = profile or Profile.from_env()
    if mode == "off":
        return AgentService(
            mode,
            journal,
            reason="The agent is off: start the API with --agent live and a provider key.",
            profile=profile,
        )
    try:
        live, models = provider() if provider is not None else live_client(critic=profile.on("critic"))
    except ProviderUnavailable as exc:
        return AgentService("off", journal, reason=f"The agent is off: {exc}.", profile=profile)
    client: LlmClient = RecordingClient(live, Cassette()) if mode == "record" else live
    spend = spend or SpendLedger()
    store = EvidenceStore()
    selector = AgentSelector(
        client, journal, mode=mode, spend=spend, profile=profile, model=models.loop, critic_model=models.critic
    )
    asker = AskRunner(client, journal, store, mode=mode, spend=spend, model=models.loop)
    return AgentService(
        mode,
        journal,
        client=client,
        selector=selector,
        store=store,
        asker=asker,
        recording=recording,
        profile=profile,
        models=models,
    )
