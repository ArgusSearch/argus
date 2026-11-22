"""HTTP views for the narrator, used by both the live and replay sources."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from argus.api.sources import LiveSource, Source
from argus.contracts.findings import Findings, Incident
from argus.contracts.graph import Graph
from argus.narrator.autonomy import Autonomy, build_autonomy
from argus.narrator.morning import MorningProjection, MorningReport, build_morning_report
from argus.narrator.run_queries import RunQueryResult, RunWindow, run_query


def _window(source: Source) -> RunWindow:
    hub = source.bus
    events = tuple(hub.history)
    return RunWindow(hub.stream, events[-1].seq if events else hub.base_seq, events)


def _snapshot(source: Source) -> tuple[RunWindow, list[Incident], Graph]:
    if isinstance(source, LiveSource):
        # The runtime publishes events and updates incident findings within one tick lock.
        with source.runtime.lock:
            return _window(source), source.incidents(), source.graph()
    # Replay advances only on the event loop. Capture all state before yielding to it.
    return _window(source), source.incidents(), source.graph()


def router(source: Source, agent_projection: MorningProjection | None = None) -> APIRouter:
    routes = APIRouter(tags=["narrator"])
    # C5 incident updates summarize C4. Retain the findings linked by issued reports so a later
    # verdict or lifecycle update cannot change the evidence behind an earlier report.
    findings_stream: str | None = None
    published_findings: dict[str, tuple[int, Findings]] = {}

    def has_receipt(receipt_id: str) -> bool:
        return source.receipt(receipt_id) is not None

    @routes.get("/report/morning", response_model=MorningReport, responses={200: {"content": {"text/markdown": {}}}})
    async def morning(format: Literal["json", "markdown"] = "json") -> MorningReport | Response:
        nonlocal findings_stream
        if isinstance(source, LiveSource):
            snapshot = await run_in_threadpool(_snapshot, source)
        else:
            snapshot = _snapshot(source)
        report, evidence = await run_in_threadpool(build_morning_report, *snapshot, has_receipt, agent_projection)
        if report.stream == source.bus.stream:
            if report.stream != findings_stream:
                published_findings.clear()
                findings_stream = report.stream
            for seq, findings in evidence.items():
                published_findings.setdefault(f"findings-{seq}", (seq, findings))
        if format == "markdown":
            return Response(report.markdown, media_type="text/markdown")
        return report

    @routes.get("/report/morning/queries/{query_id}")
    async def query(query_id: str, stream: str, through_seq: Annotated[int, Query(ge=0)]) -> RunQueryResult:
        current = _window(source)
        if current.stream != stream or through_seq > current.through_seq:
            raise HTTPException(404, "Run prefix unavailable")
        events = tuple(event for event in current.events if event.seq <= through_seq)
        if (events[-1].seq if events else source.bus.base_seq) != through_seq:
            raise HTTPException(404, "Run prefix unavailable")
        finding = published_findings.get(query_id) if stream == findings_stream else None
        if finding is not None and finding[0] > through_seq:
            raise HTTPException(404, "Query unavailable for this run prefix")
        result = await run_in_threadpool(run_query, RunWindow(stream, through_seq, events), query_id, finding)
        if result is None:
            raise HTTPException(404, "Query unavailable for this run prefix")
        return result

    @routes.get("/autonomy")
    def autonomy() -> Autonomy:
        return build_autonomy(source.graph())

    return routes
