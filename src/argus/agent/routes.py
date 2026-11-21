"""HTTP routes of the agent (docs/ext/agent.md), outside the C5 `ROUTES` tuple like the narrator and demo routers.

Live sources carry an `AgentService` (`source.agent`). Any other source answers health with `enabled: false`
and an empty activity log, so the web can probe once and hide its panels.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from argus.agent.ask import AskScope
from argus.agent.journal import Journal
from argus.agent.provider import ProviderUnavailable
from argus.agent.service import AgentService
from argus.agent.types import ReceiptLink, RunSummary
from argus.api.sources import LiveSource, Source
from argus.contracts.events import EventType
from argus.contracts.findings import Receipt


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    incident_id: str | None = None
    conversation_id: str | None = None
    request_id: str | None = None


def _service(source: Source) -> AgentService:
    found = getattr(source, "agent", None)
    if isinstance(found, AgentService):
        return found
    reason = (
        "This is a replay: the recorded agent run plays in the demo playback (/demo)."
        if source.mode == "replay"
        else "The agent is off."
    )
    return AgentService("off", Journal(stream=source.bus.stream), reason=reason)


def _scope(source: Source) -> AskScope:
    if not isinstance(source, LiveSource):
        raise HTTPException(409, "Ask needs a live run over a world: make demo with --agent live.")
    hub = source.bus
    tick = next((e for e in reversed(hub.history) if e.type is EventType.TICK), None)
    if tick is None or hub.state.last_tick is None:
        raise HTTPException(409, "The run has not completed its first hour yet.")
    return AskScope(
        stream=hub.stream,
        through_seq=hub.last_seq,
        as_of=tick.sim_ts,
        latest_hour=hub.state.last_tick.hour,
        graph=source.graph(),
        incidents=source.incidents(),
        world=source.runtime.world,
    )


def router(source: Source) -> APIRouter:
    routes = APIRouter(prefix="/agent", tags=["agent"])
    off = _service(source)

    def service() -> AgentService:
        found = getattr(source, "agent", None)
        return found if isinstance(found, AgentService) else off

    @routes.get("/health")
    def health() -> dict[str, Any]:
        return service().health()

    @routes.get("/activity")
    def activity(since: int = 0) -> dict[str, Any]:
        svc = service()
        records = svc.journal.since(since)
        return {
            "stream": source.bus.stream,
            "mode": svc.mode,
            "records": [r.model_dump(mode="json") for r in records],
            "next_cursor": records[-1].seq if records else since,
        }

    @routes.get("/runs")
    def runs() -> list[RunSummary]:
        return list(service().journal.runs.values())

    @routes.post("/ask")
    async def ask(body: AskBody) -> dict[str, Any]:
        svc = service()
        if not svc.enabled:
            raise HTTPException(409, svc.reason)
        scope = await run_in_threadpool(_scope, source)
        cursor = svc.journal.records[-1].seq if svc.journal.records else 0
        try:
            result = await run_in_threadpool(svc.ask, body.question, scope, body.incident_id, body.conversation_id)
        except ProviderUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        if result.status == "unknown_conversation":
            raise HTTPException(404, result.reason or "unknown conversation")
        return result.to_json(cursor)

    if getattr(source, "remediation", None) is None:  # otherwise lane C's operator router serves /agent/actions

        @routes.get("/actions")
        def actions() -> list[dict[str, Any]]:
            return []

        @routes.get("/actions/{action_id}")
        def action(action_id: str) -> dict[str, Any]:
            raise HTTPException(404, f"no action {action_id}")

    @routes.get("/receipts/{run_id}/{world_revision}/{receipt_id}")
    def receipt(run_id: str, world_revision: str, receipt_id: str) -> Receipt:
        svc = service()
        ref = ReceiptLink(run_id=run_id, world_revision=world_revision, receipt_id=receipt_id)
        if svc.store is not None:
            ctx = svc.store.context_for(source.bus.stream, ref, through_seq=source.bus.last_seq, as_of=datetime.max)
            if ctx is not None:
                found = svc.store.inspect_receipt(ctx, ref)
                if found is not None:
                    return found
        remediation = getattr(source, "remediation", None)
        if remediation is not None and (found := remediation.receipt(ref)) is not None:
            return found
        # an investigation run cites the runtime's own receipts: serve only those it cited, in its revision
        if svc.journal.cited(ref) and (found := source.receipt(receipt_id)) is not None:
            return found
        raise HTTPException(404, f"no receipt {ref.key()}")

    return routes
