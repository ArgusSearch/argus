"""FastAPI service for C5: the SSE event stream, the REST routes and the Mission Control page.

A `Source` (`argus.api.sources`) runs the run: `LiveSource` drives the runtime over a world,
`ReplaySource` replays a recording. Both publish through one `EventHub`.

SSE (`GET /events`): each event is `id: <seq>`, `event: <type>`, `data: <Event JSON>` (contract C5).
`since=<seq>` or `Last-Event-ID` resumes, `limit=<n>` ends the stream after n events. Replay restarts
start a new stream whose seq continues after the old one; a client that was following, or resumes
from an older stream, first gets `event: stream` with `{"stream", "mode"}` and must drop its state.
"""

from __future__ import annotations

import json
import signal
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from argus.agent.routes import router as agent_router
from argus.api.digest import Digest, build_digest
from argus.api.hub import EventHub
from argus.api.rerun import RerunResult, RerunUnavailable
from argus.api.sources import ControlError, Source
from argus.api.state import ALARM_Z, PAIR_Z, WIGGLE_Z
from argus.contracts import CONTRACT_VERSION
from argus.contracts.events import ROUTES
from argus.contracts.findings import Incident, Note, Receipt
from argus.contracts.graph import Graph
from argus.counterfactual.api import router as counterfactual_router
from argus.demo.api import create_router as demo_router
from argus.graph.store import REPO
from argus.narrator.routes import router as narrator_router

WEB_DIST = REPO / "web" / "dist"


class RunControl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["play", "pause", "restart", "end"] | None = None
    speed: float | None = Field(default=None, gt=0)


def end_streams_on_exit(hub: EventHub) -> Callable[[], None]:
    """Make the first Ctrl+C (or SIGTERM) end every SSE stream, then hand the signal on.

    uvicorn waits for open responses to finish before it runs the lifespan shutdown, and an event
    stream never finishes by itself: without this, stopping the server hangs while a page is open.
    Returns a function that restores the previous handlers. Does nothing outside the main thread.
    """
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    def handler(signum: int, frame: Any) -> None:
        hub.close()
        prev = previous[signal.Signals(signum)]
        if callable(prev):
            prev(signum, frame)
        else:  # SIG_DFL or SIG_IGN: let the default behaviour happen
            signal.signal(signum, prev)
            signal.raise_signal(signum)

    for sig in previous:
        signal.signal(sig, handler)

    def restore() -> None:
        for sig, prev in previous.items():
            if signal.getsignal(sig) is handler:
                signal.signal(sig, prev)

    return restore


def create_app(source: Source, start: bool = True, web_dist: Path = WEB_DIST) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        restore = end_streams_on_exit(source.bus)
        if start:
            source.start()
        try:
            yield
        finally:
            restore()
            source.bus.close()
            source.stop()
            await source.closed()

    app = FastAPI(
        title="Argus",
        version=CONTRACT_VERSION,
        description="The analyst that never sleeps. Contract C5: REST routes plus the SSE stream at /events.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
    app.include_router(narrator_router(source))
    app.include_router(counterfactual_router(source))
    app.include_router(agent_router(source))
    remediation = getattr(source, "remediation", None)
    if remediation is not None:
        from argus.remediation import create_router as remediation_router

        app.include_router(remediation_router(remediation))
    hub = source.bus

    # ------------------------------------------------------------------ run and stream

    @app.get("/health")
    def health() -> dict[str, Any]:
        last = hub.history[-1] if hub.history else None
        return {
            "status": "ok",
            "mode": source.mode,
            "contract_version": CONTRACT_VERSION,
            "stream": hub.stream,
            "events": len(hub.history),
            "last_seq": hub.last_seq,
            "sim_ts": last.sim_ts.isoformat() if last else None,
            "run": source.status(),
            "thresholds": {"alarm_z": ALARM_Z, "pair_z": PAIR_Z, "wiggle_z": WIGGLE_Z},
            **source.describe(),
        }

    @app.get("/routes")
    def routes() -> list[dict[str, str]]:
        return [r.model_dump() for r in ROUTES]

    @app.get("/events", response_class=EventSourceResponse)
    async def events(
        since: int = 0, limit: int | None = None, last_event_id: str | None = Header(None)
    ) -> AsyncIterator[ServerSentEvent]:
        """The history after `since` (or Last-Event-ID), then live events."""
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else since
        sent = 0
        async for item in hub.follow(after):
            if item.event is None:
                header = {"stream": item.stream, "mode": source.mode}
                yield ServerSentEvent(event="stream", raw_data=json.dumps(header))
                continue
            yield ServerSentEvent(
                raw_data=item.event.model_dump_json(), event=item.event.type.value, id=str(item.event.seq)
            )
            sent += 1
            if limit is not None and sent >= limit:
                return

    @app.post("/replay")
    async def control(body: RunControl) -> dict[str, Any]:
        """Pace, pause, finish or restart the run. Async: it runs on the loop that runs the replayer."""
        try:
            return source.control(body.action, body.speed)
        except ControlError as exc:
            raise HTTPException(409, str(exc)) from exc

    # ------------------------------------------------------------------ graph, incidents, notes, receipts

    @app.get("/graph")
    def graph() -> Graph:
        return source.graph()

    @app.get("/incidents")
    def incidents() -> list[Incident]:
        return sorted(source.incidents(), key=lambda i: (i.opened_at, i.id), reverse=True)

    def _incident(incident_id: str) -> Incident:
        found = next((i for i in source.incidents() if i.id == incident_id), None)
        if found is None:
            raise HTTPException(404, f"no incident {incident_id}")
        return found

    @app.get("/incidents/{incident_id}")
    def incident(incident_id: str) -> Incident:
        return _incident(incident_id)

    @app.get("/incidents/{incident_id}/report", response_class=PlainTextResponse)
    def report(incident_id: str) -> PlainTextResponse:
        text = source.report(incident_id)
        if text is None:
            raise HTTPException(404, f"no incident {incident_id}")
        return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")

    @app.get("/digest")
    def digest() -> Digest:
        """'While you slept': the run so far in a few lines, each with its receipts (narrator)."""
        return build_digest(hub.state, source.incidents(), source.graph())

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
    def rerun(receipt_id: str) -> RerunResult:
        if source.receipt(receipt_id) is None:
            raise HTTPException(404, f"no receipt {receipt_id}")
        try:
            result = source.rerun(receipt_id)
        except RerunUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        if result is None:
            raise HTTPException(
                409, "replay mode has no world to re-run against: `make demo` runs Argus live over the S1 world"
            )
        return result

    # ------------------------------------------------------------------ routes owned by other lanes

    for route in [r for r in ROUTES if r.status == "stub"]:

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

    # ------------------------------------------------------------------ Mission Control

    if (web_dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(web_dist / "index.html")

        @app.get("/favicon.svg", include_in_schema=False)
        def favicon() -> FileResponse:
            return FileResponse(web_dist / "favicon.svg")
    else:

        @app.get("/", include_in_schema=False)
        def index_missing() -> HTMLResponse:
            return HTMLResponse(
                "<!doctype html><title>Argus API</title><body style='font:15px system-ui;padding:2rem'>"
                "<h1>Argus API</h1><p>Mission Control is not built yet: "
                "<code>npm --prefix web install && npm --prefix web run build</code>, then reload. "
                "During development run <code>npm --prefix web run dev</code>.</p>"
                "<p><a href='/docs'>API docs</a> · <a href='/health'>health</a></p></body>"
            )

    app.include_router(demo_router(hub))
    return app
