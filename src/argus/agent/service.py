"""The agent inside the API process: one journal, the pre-verdict selector for the runtime, Ask, and health.

`build(mode)` is called by `LiveSource`. Live and record modes need `ANTHROPIC_API_KEY`; without it, or with
mode `off`, the runtime runs Stage 2 alone and `/agent/health` says why. Replay mode is served by the demo
playback (lane F); this service then only reports itself as off for live work.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from argus.agent.ask import AskResult, AskRunner, AskScope
from argus.agent.investigate import AgentSelector, Budget
from argus.agent.journal import Journal
from argus.agent.provider import (
    LOOP_MODEL,
    SYNTHESIS_MODEL,
    AnthropicClient,
    Cassette,
    ProviderUnavailable,
    RecordingClient,
    SpendLedger,
)
from argus.agent.types import INTERFACE_VERSION, AgentMode, LlmClient
from argus.evidence import EvidenceStore

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
    conversations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def health(self) -> dict[str, Any]:
        runs = list(self.journal.runs.values())
        budget = Budget()
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "reason": self.reason,
            "interface_version": INTERFACE_VERSION,
            "models": {"loop": LOOP_MODEL, "synthesis": SYNTHESIS_MODEL},
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
        }

    def ask(
        self, question: str, scope: AskScope, incident_id: str | None, conversation_id: str | None = None
    ) -> AskResult:
        """A question, optionally following up an earlier one: the conversation keeps its incident scope and
        hands the earlier questions and answers to the model as context (never as evidence: every figure
        is verified again in the new run)."""
        if self.asker is None:
            raise ProviderUnavailable(self.reason or "the agent is off")
        with self.lock:  # one question at a time keeps cost and the activity log readable
            if conversation_id is not None and conversation_id not in self.conversations:
                return AskResult(status="unknown_conversation", run_id="", reason=f"no conversation {conversation_id}")
            conversation_id = conversation_id or f"conv_{len(self.conversations) + 1:04d}"
            turns = self.conversations.setdefault(conversation_id, [])
            incident_id = incident_id or next((t["incident_id"] for t in turns if t["incident_id"]), None)
            result = self.asker.ask(question, scope, incident_id, history=turns)
            result.conversation_id = conversation_id
            turns.append({"question": question, "answer": result.answer, "incident_id": incident_id})
        self.save()
        return result

    def save(self) -> None:
        """Record mode: write the cassette after every run so a crash keeps what was paid for."""
        if self.recording is not None and isinstance(self.client, RecordingClient):
            self.client.cassette.write(self.recording / "turns.jsonl")


def build(mode: AgentMode, stream: str = "local", recording: Path | None = None) -> AgentService:
    journal = Journal(stream=stream)
    if mode == "off":
        return AgentService(
            mode, journal, reason="The agent is off: start the API with --agent live (needs ANTHROPIC_API_KEY)."
        )
    try:
        live: LlmClient = AnthropicClient()
    except ProviderUnavailable as exc:
        return AgentService("off", journal, reason=f"The agent is off: {exc}.")
    client: LlmClient = RecordingClient(live, Cassette()) if mode == "record" else live
    spend = SpendLedger()
    store = EvidenceStore()
    selector = AgentSelector(client, journal, mode=mode, spend=spend)
    asker = AskRunner(client, journal, store, mode=mode, spend=spend)
    return AgentService(mode, journal, client=client, selector=selector, store=store, asker=asker, recording=recording)
