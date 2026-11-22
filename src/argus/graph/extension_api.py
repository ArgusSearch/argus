"""REST routes of the graph extension: onboard a metric (C2) into the running graph and read the proof.

An extension router mounted by plain import (like /demo and /counterfactual): it is not part of the frozen C5
route table. Its documentation is docs/ext/graph-extension.md.

| route                          | what it does                                                        |
|--------------------------------|---------------------------------------------------------------------|
| `POST /graph/metrics`          | place one metric; the result carries certificate, edges and repair  |
| `GET /graph/metrics`           | every placement of this stream, plus the recorded demo pack         |
| `GET /graph/metrics/{name}`    | one placement                                                       |

The body is a C2 metric as JSON (`name`, `description`, `sql`) or the YAML file itself
(`content-type: application/yaml`). Every verdict, REJECTED included, is a 200 with a `PlacementResult`;
409 means the placement cannot run here (a replay asked for a metric it has no recording of).
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from argus.api.sources import Source
from argus.contracts.metric import MetricDefinition
from argus.graph.extension import ExtensionState, GraphExtension, PlacementError, PlacementResult, load_recorded
from argus.remediation.api import OperatorGate

PUBLIC_PLACEMENT_LIMIT = 5
PUBLIC_WRITES_PER_MINUTE = 16
PUBLIC_METRIC_BODY_LIMIT = 16 * 1024

_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": MetricDefinition.model_json_schema()},
            "application/yaml": {"schema": {"type": "string", "description": "the metric YAML file (C2)"}},
        },
    }
}


def extension_for(source: Source) -> GraphExtension:
    """The extension service of a source: live when it runs a runtime over a world, recorded otherwise."""
    return GraphExtension(source.bus, source.mode, runtime=getattr(source, "runtime", None))


@dataclass
class _SessionExtension:
    extension: GraphExtension
    minute: int = -1
    attempts: int = 0


class PublicGraphExtensions:
    """Private overlays on a shared graph. All placements use trusted, checked-in proof data."""

    def __init__(self, source: Source, gate: OperatorGate) -> None:
        self.source = source
        self.gate = gate
        self.recorded = load_recorded()
        self.base = GraphExtension(source.bus, source.mode, recorded=self.recorded)
        self._sessions: dict[str, _SessionExtension] = {}
        self._lock = Lock()

    def read(self, request: Request) -> GraphExtension | None:
        with self._lock:
            session = self._sessions.get(self.gate.session_id(request) or "")
            return session.extension if session else None

    def write(self, request: Request) -> GraphExtension:
        with self._lock:
            sid = self.gate.require_session(request)
            session = self._sessions.get(sid)
            if session is None:
                active = self.gate.active_sessions()
                self._sessions = {key: value for key, value in self._sessions.items() if key in active}
                session = _SessionExtension(
                    GraphExtension(
                        self.source.bus,
                        self.source.mode,
                        isolated=True,
                        recorded=self.recorded,
                        placement_limit=PUBLIC_PLACEMENT_LIMIT,
                    )
                )
                self._sessions[sid] = session
            minute = int(monotonic() // 60)
            if minute != session.minute:
                session.minute, session.attempts = minute, 0
            if session.attempts >= PUBLIC_WRITES_PER_MINUTE:
                raise HTTPException(429, "Too many metric placement requests", headers={"Retry-After": "60"})
            session.attempts += 1
            return session.extension


async def _metric(request: Request, *, public: bool = False) -> MetricDefinition:
    raw = await request.body()
    if public and len(raw) > PUBLIC_METRIC_BODY_LIMIT:
        raise HTTPException(413, "Metric definition too large")
    try:
        if "yaml" in request.headers.get("content-type", ""):
            data: Any = yaml.safe_load(raw)
        else:
            data = await request.json()
        return MetricDefinition.model_validate(data)
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        if public:
            raise HTTPException(422, "Invalid metric definition") from exc
        # YAML can decode dates, bytes and other non-JSON values. Do not echo them into the JSON error body.
        detail = (
            exc.errors(include_url=False, include_input=False, include_context=False)
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        raise HTTPException(422, detail) from exc


def create_router(extension: GraphExtension, public: PublicGraphExtensions | None = None) -> APIRouter:
    router = APIRouter(tags=["Graph extension"])

    def for_read(request: Request) -> GraphExtension:
        return (public.read(request) or public.base) if public else extension

    async def place(request: Request) -> PlacementResult:
        target = public.write(request) if public else extension
        metric = await _metric(request, public=public is not None)
        try:
            result, _new = await run_in_threadpool(target.place, metric)
        except PlacementError as exc:
            raise HTTPException(409, str(exc)) from exc
        return result

    router.add_api_route(
        "/graph/metrics",
        place,
        methods=["POST"],
        response_model=PlacementResult,
        summary="place a new metric (C2) in the running graph",
        openapi_extra=_BODY,
    )

    @router.get("/graph/metrics")
    def placements(request: Request) -> ExtensionState:
        return for_read(request).state()

    @router.get("/graph/metrics/{name}")
    def placement(name: str, request: Request) -> PlacementResult:
        found = for_read(request).get(name)
        if found is None:
            raise HTTPException(404, f"no placement of {name} in this stream")
        return found

    return router
