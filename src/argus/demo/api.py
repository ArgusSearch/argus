"""HTTP controls and cue streaming for Mission Control demo mode."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.sse import EventSourceResponse, ServerSentEvent

from argus.api.hub import EventHub
from argus.contracts.findings import Receipt
from argus.contracts.graph import Graph
from argus.demo.contracts import ControlDemo, DemoBeat, DemoState, StartDemo
from argus.demo.playback import ControlError, Playback, PlaybackRun
from argus.demo.timeline import load_timeline


def create_router(hub: EventHub) -> APIRouter:
    router = APIRouter(prefix="/demo", tags=["Demo"])
    playback = Playback()

    @router.post("/start")
    async def start_demo(body: StartDemo) -> DemoState:
        try:
            timeline = await run_in_threadpool(load_timeline, body.scenario)
        except (OSError, ValueError) as exc:
            raise HTTPException(503, f"demo recording unavailable for {body.scenario}") from exc
        return playback.start(timeline, body.speed)

    @router.get("/state")
    async def demo_state() -> DemoState:
        return playback.state()

    @router.post("/control")
    async def control_demo(body: ControlDemo) -> DemoState:
        try:
            return playback.control(body.action)
        except ControlError as exc:
            raise HTTPException(409, str(exc)) from exc

    def active_run(run_id: str | None, *, stale_status: int = 409) -> PlaybackRun:
        run = playback.run
        if run is None:
            raise HTTPException(409, "start a demo first")
        if run_id is not None and run.id != run_id:
            raise HTTPException(stale_status, "demo run was replaced")
        return run

    @router.get("/graph")
    async def demo_graph(run_id: str | None = None) -> Graph:
        return active_run(run_id).timeline.graph

    @router.get("/receipts/{receipt_id}")
    async def demo_receipt(receipt_id: str, run_id: str | None = None) -> Receipt:
        run = active_run(run_id)
        beat = run.state(playback.clock()).beat_index
        introduced = run.timeline.receipt_beats.get(receipt_id)
        receipt = run.timeline.receipts.get(receipt_id)
        if receipt is None or introduced is None or beat is None or introduced > beat:
            raise HTTPException(404, f"no released demo receipt {receipt_id}")
        return receipt

    async def stream_cursor(
        run_id: str | None = None, last_event_id: Annotated[str | None, Header()] = None
    ) -> tuple[PlaybackRun, int]:
        if last_event_id:
            previous, _, index = last_event_id.rpartition(":")
            run = active_run(run_id or previous, stale_status=204)
            if previous != run.id:
                raise HTTPException(204)
            if not index.isascii() or not index.isdecimal() or len(index) > 8 or int(index) >= len(run.timeline.cues):
                raise HTTPException(422, "invalid Last-Event-ID")
            return run, int(index) + 1
        return active_run(run_id, stale_status=204), 0

    @router.get("/events", response_class=EventSourceResponse)
    async def demo_events(
        cursor: Annotated[tuple[PlaybackRun, int], Depends(stream_cursor)],
    ) -> AsyncIterator[ServerSentEvent]:
        run, next_index = cursor
        while playback.run is run and not hub.closed:
            now = playback.clock()
            state = run.state(now)
            assert state.beat_index is not None
            if next_index <= state.beat_index:
                cue = run.timeline.cues[next_index]
                beat = DemoBeat(**cue.model_dump(), run_id=run.id, scenario=run.timeline.scenario)
                yield ServerSentEvent(event="beat", id=f"{run.id}:{next_index}", raw_data=beat.model_dump_json())
                next_index += 1
                continue
            if state.status == "completed":
                yield ServerSentEvent(event="complete", raw_data=state.model_dump_json())
                return

            delay = run.delay(now, next_index)
            # The hub's signal handler closes all streams on exit, including a paused demo.
            timeout = min(delay, 1.0) if delay is not None else 1.0
            with suppress(TimeoutError):
                await asyncio.wait_for(playback.changed.wait(), timeout)

    return router
