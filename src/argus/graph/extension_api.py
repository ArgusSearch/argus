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

from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from argus.api.sources import Source
from argus.contracts.metric import MetricDefinition
from argus.graph.extension import ExtensionState, GraphExtension, PlacementError, PlacementResult

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


async def _metric(request: Request) -> MetricDefinition:
    raw = await request.body()
    try:
        if "yaml" in request.headers.get("content-type", ""):
            data: Any = yaml.safe_load(raw)
        else:
            data = await request.json()
        return MetricDefinition.model_validate(data)
    except (ValueError, yaml.YAMLError, ValidationError) as exc:
        detail = exc.errors(include_url=False) if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(422, detail) from exc


def create_router(extension: GraphExtension) -> APIRouter:
    router = APIRouter(tags=["Graph extension"])

    async def place(request: Request) -> PlacementResult:
        metric = await _metric(request)
        try:
            result, _new = await run_in_threadpool(extension.place, metric)
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
    def placements() -> ExtensionState:
        return extension.state()

    @router.get("/graph/metrics/{name}")
    def placement(name: str) -> PlacementResult:
        found = extension.get(name)
        if found is None:
            raise HTTPException(404, f"no placement of {name} in this stream")
        return found

    return router
