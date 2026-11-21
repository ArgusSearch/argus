"""HTTP controls and cue streaming for Mission Control demo mode."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from argus.api.hub import EventHub
from argus.contracts.events import Event
from argus.contracts.findings import Incident, Receipt
from argus.contracts.graph import Graph
from argus.counterfactual.models import CounterfactualResult
from argus.counterfactual.replay import ReplayUnavailable
from argus.demo.agent import AgentTimeline, load_agent_timeline
from argus.demo.contracts import AgentDemoState, ControlDemo, DemoBeat, DemoState, Scenario, StartDemo
from argus.demo.playback import ControlError, Playback, PlaybackRun
from argus.demo.timeline import DemoReport, Timeline, load_counterfactual, load_timeline
from argus.narrator.morning import MorningReport as NarratorReport
from argus.narrator.run_queries import RunQueryResult, run_query


class AgentSnapshot(BaseModel):
    state: AgentDemoState
    events: tuple[Event, ...]
    incidents: list[Incident]


def create_router(
    hub: EventHub,
    *,
    playback: Playback | None = None,
    allow_agent: bool = False,
    agent_loader: Callable[[Scenario], AgentTimeline] = load_agent_timeline,
) -> APIRouter:
    router = APIRouter(prefix="/demo", tags=["Demo"])
    playback = playback or Playback()

    @router.post("/start", response_model=AgentDemoState | DemoState)
    async def start_demo(body: StartDemo) -> DemoState:
        if body.variant == "agent" and not allow_agent:
            raise HTTPException(409, "agent demo requires a replay server")
        loader: Callable[[Scenario], Timeline | AgentTimeline] = (
            agent_loader if body.variant == "agent" else load_timeline
        )
        try:
            timeline = await run_in_threadpool(loader, body.scenario)
        except (OSError, ValueError) as exc:
            detail = f"demo recording unavailable for {body.scenario}"
            if body.variant == "agent":
                detail = f"agent {detail}: {exc}"
            raise HTTPException(503, detail) from exc
        return playback.start(timeline, body.speed)

    @router.get("/state", response_model=AgentDemoState | DemoState)
    async def demo_state() -> DemoState:
        return playback.state()

    @router.post("/control", response_model=AgentDemoState | DemoState)
    async def control_demo(body: ControlDemo, run_id: str | None = None) -> DemoState:
        active_run(run_id)
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
        if run_id is None and isinstance(run.timeline, AgentTimeline):
            raise HTTPException(409, "agent demo requires its run_id")
        return run

    @router.get("/snapshot")
    async def demo_snapshot(run_id: str) -> AgentSnapshot:
        active_run(run_id)
        try:
            view = playback.agent_view(run_id)
        except ControlError as exc:
            raise HTTPException(404, str(exc)) from exc
        return AgentSnapshot(state=view.state, events=view.events, incidents=view.incidents)

    @router.get("/graph")
    async def demo_graph(run_id: str | None = None) -> Graph:
        return active_run(run_id).timeline.graph

    def released_receipt(receipt_id: str, run_id: str | None) -> Receipt:
        run = active_run(run_id)
        if isinstance(run.timeline, AgentTimeline):
            proof = playback.agent_view(run.id).receipts.get(receipt_id)
            if proof is None or "/" in receipt_id:
                raise HTTPException(404, f"no released demo receipt {receipt_id}")
            return proof.receipt
        beat = run.state(playback.clock()).beat_index
        introduced = run.timeline.receipt_beats.get(receipt_id)
        receipt = run.timeline.receipts.get(receipt_id)
        if receipt is None or introduced is None or beat is None or introduced > beat:
            raise HTTPException(404, f"no released demo receipt {receipt_id}")
        return receipt

    @router.get("/receipts/{receipt_id}")
    async def demo_receipt(receipt_id: str, run_id: str | None = None) -> Receipt:
        return released_receipt(receipt_id, run_id)

    @router.post("/receipts/{receipt_id}/rerun", responses={404: {}, 409: {}})
    async def demo_rerun(receipt_id: str, run_id: str | None = None) -> None:
        released_receipt(receipt_id, run_id)
        raise HTTPException(409, "demo playback has no world to re-run against; the receipt keeps its SQL and hash")

    @router.get("/counterfactual", responses={404: {}, 409: {}})
    async def demo_counterfactual(run_id: str | None = None) -> CounterfactualResult:
        run = active_run(run_id)
        if not isinstance(run.timeline, Timeline):
            raise HTTPException(404, "the agent demo serves its recorded action effect")
        beat = run.state(playback.clock()).beat_index
        if beat is None or beat < run.timeline.beat("verdict"):
            raise HTTPException(404, "the demo has not reached its verdict beat")
        try:
            return await run_in_threadpool(load_counterfactual, run.timeline.scenario)
        except ReplayUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc

    def released_report(run_id: str | None) -> DemoReport:
        run = active_run(run_id)
        index = run.state(playback.clock()).beat_index
        if index is None or not any(cue.kind == "morning_report" for cue in run.timeline.cues[: index + 1]):
            raise HTTPException(404, "the demo has not reached its morning_report beat")
        report = run.timeline.report
        assert report is not None
        return report

    @router.get("/report/morning", response_model=NarratorReport, responses={200: {"content": {"text/markdown": {}}}})
    async def demo_morning_report(
        run_id: str | None = None, format: Literal["json", "markdown"] = "json"
    ) -> NarratorReport | Response:
        report = released_report(run_id).report
        if run_id and isinstance(active_run(run_id).timeline, AgentTimeline):
            report = _scoped_report(report, run_id)
        if format == "markdown":
            return Response(report.markdown, media_type="text/markdown")
        return report

    @router.get("/report/morning/queries/{query_id}")
    async def demo_report_query(
        query_id: str, stream: str, through_seq: Annotated[int, Query(ge=0)], run_id: str | None = None
    ) -> RunQueryResult:
        demo = released_report(run_id)
        if (stream, through_seq) != (demo.window.stream, demo.window.through_seq):
            raise HTTPException(404, "Run prefix unavailable")
        result = await run_in_threadpool(run_query, demo.window, query_id, demo.findings.get(query_id))
        if result is None:
            raise HTTPException(404, "Query unavailable for this run prefix")
        return result

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


def _scoped_report(report: NarratorReport, run_id: str) -> NarratorReport:
    """Make links from an agent report expire with the demo session."""
    replacements: dict[str, str] = {}

    def bind(data: object) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                if key in {"href", "rerun_href"} and isinstance(value, str):
                    connector = "&" if "?" in value else "?"
                    replacements[value] = data[key] = f"{value}{connector}run_id={run_id}"
                else:
                    bind(value)
        elif isinstance(data, list):
            for value in data:
                bind(value)

    payload = report.model_dump()
    bind(payload)
    for url, scoped in replacements.items():
        payload["markdown"] = payload["markdown"].replace(f"]({url})", f"]({scoped})")
    return NarratorReport.model_validate(payload)
