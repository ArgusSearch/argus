"""FastAPI app: the REST routes and the SSE stream of contract C5 (`argus.contracts.events.ROUTES`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from argus.api.sources import Source
from argus.contracts import CONTRACT_VERSION
from argus.contracts.events import ROUTES, Event
from argus.contracts.findings import Incident, Note, Receipt
from argus.contracts.graph import Graph


def _sse(event: Event) -> ServerSentEvent:
    return ServerSentEvent(raw_data=event.model_dump_json(), event=event.type.value, id=str(event.seq))


def create_app(source: Source, start: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if start:
            source.start()
        yield
        source.stop()

    app = FastAPI(
        title="Argus",
        version=CONTRACT_VERSION,
        description="The analyst that never sleeps. Contract C5: REST routes plus the SSE stream at /events.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        last = source.bus.history[-1] if source.bus.history else None
        return {
            "status": "ok",
            "mode": source.mode,
            "contract_version": CONTRACT_VERSION,
            "events": len(source.bus.history),
            "sim_ts": last.sim_ts.isoformat() if last else None,
        }

    @app.get("/routes")
    def routes() -> list[dict[str, str]]:
        return [r.model_dump() for r in ROUTES]

    @app.get("/events", response_class=EventSourceResponse)
    async def events(
        request: Request, since: int = 0, limit: int | None = None, last_event_id: str | None = Header(None)
    ) -> AsyncIterator[ServerSentEvent]:
        """Replays the history after `since` (or the Last-Event-ID header), then streams live events."""
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else since
        queue, history = source.bus.subscribe()
        sent = 0
        try:
            for event in history:
                if event.seq > after:
                    yield _sse(event)
                    sent += 1
                    if limit is not None and sent >= limit:
                        return
            while True:
                event = await queue.get()
                if event.seq <= after:
                    continue
                yield _sse(event)
                sent += 1
                if limit is not None and sent >= limit:
                    return
        finally:
            source.bus.unsubscribe(queue)

    @app.get("/graph")
    def graph() -> Graph:
        return source.graph()

    @app.get("/incidents")
    def incidents() -> list[Incident]:
        return sorted(source.incidents(), key=lambda i: i.opened_at, reverse=True)

    def _incident(incident_id: str) -> Incident:
        for inc in source.incidents():
            if inc.id == incident_id:
                return inc
        raise HTTPException(404, f"no incident {incident_id}")

    @app.get("/incidents/{incident_id}")
    def incident(incident_id: str) -> Incident:
        return _incident(incident_id)

    @app.get("/incidents/{incident_id}/report", response_class=PlainTextResponse)
    def report(incident_id: str) -> str:
        text = source.report(incident_id)
        if text is None:
            raise HTTPException(404, f"no incident {incident_id}")
        return text

    @app.get("/notes")
    def notes() -> list[Note]:
        return source.notes()

    @app.get("/receipts/{receipt_id}")
    def receipt(receipt_id: str) -> Receipt:
        found = source.receipt(receipt_id)
        if found is None:
            raise HTTPException(404, f"no receipt {receipt_id}")
        return found

    @app.post("/receipts/{receipt_id}/rerun")
    def rerun(receipt_id: str) -> dict[str, Any]:
        found = source.receipt(receipt_id)
        if found is None:
            raise HTTPException(404, f"no receipt {receipt_id}")
        result = source.rerun(receipt_id)
        if result is None:
            raise HTTPException(409, "replay mode has no world to re-run against; start the API with --world")
        new_hash, matches = result
        return {
            "id": receipt_id,
            "as_of": found.as_of,
            "hash": new_hash,
            "expected": found.result_hash,
            "matches": matches,
        }

    stubs = [r for r in ROUTES if r.status == "stub"]
    for route in stubs:

        def stub(_route: Any = route) -> JSONResponse:
            return JSONResponse(
                status_code=501,
                content={
                    "detail": f"{_route.summary}: not built yet",
                    "owner": f"lane {_route.owner}",
                    "contract": "C5",
                },
            )

        app.add_api_route(route.path, stub, methods=[route.method], summary=f"{route.summary} (stub)")
    return app
