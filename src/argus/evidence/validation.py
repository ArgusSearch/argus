"""Validate the agent's read capabilities before invoking the shared toolbox."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from argus.contracts.findings import EvidenceRef, Segment, Window
from argus.contracts.graph import Graph, NodeKind
from argus.contracts.tools import (
    TOOL_MODELS,
    CheckFreshnessInput,
    CheckIdentitiesInput,
    DecomposeFormulaInput,
    HoldoutCheckInput,
    ListEventsInput,
    MixRateSplitInput,
    PlaceboTestInput,
    SegmentSearchInput,
)
from argus.contracts.world import DIMENSIONS, EVIDENCE_LOGS, FACT_TABLES
from argus.graph.store import product_factors
from argus.investigate.tools import StageTwoToolbox
from argus.investigator.tools import covers

HOUR = timedelta(hours=1)
_FACT_NAMES = frozenset(spec.name for spec in FACT_TABLES)


class ControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anomaly_id: str


class CounterfactualInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: str


EXTENSION_MODELS: dict[str, type[BaseModel]] = {
    "check_control_group": ControlInput,
    "counterfactual": CounterfactualInput,
}


def c6_names() -> tuple[str, ...]:
    return tuple(name for name in TOOL_MODELS if callable(getattr(StageTwoToolbox, f"_run_{name}", None)))


def _check_segment(segment: Segment, allowed: Mapping[str, Any] | list[str]) -> None:
    if any(dim not in allowed or value not in DIMENSIONS.get(dim, ()) for dim, value in segment.items()):
        raise ValueError("The segment contains an unavailable dimension or value.")


def utc(ts: datetime) -> datetime:
    if ts.tzinfo is not None and ts.utcoffset() != timedelta(0):
        raise ValueError("Use UTC times.")
    return ts.replace(tzinfo=None)


def utc_window(window: Window) -> Window:
    return Window(start=utc(window.start), end=utc(window.end))


def c6_input(
    name: str,
    args: dict[str, Any],
    *,
    graph: Graph,
    as_of: datetime,
    latest_hour: datetime,
    events: Mapping[tuple[str, str], EvidenceRef],
    source_clocks: Mapping[str, tuple[datetime, datetime]] | None = None,
) -> BaseModel:
    data = TOOL_MODELS[name][0].model_validate(args)
    if isinstance(data, ListEventsInput):
        data.start, data.end = utc(data.start), utc(data.end)
        if (
            not data.start <= data.end <= as_of
            or data.end - data.start > 48 * HOUR
            or (data.logs is not None and (not data.logs or set(data.logs) - set(EVIDENCE_LOGS)))
        ):
            raise ValueError("Use a visible log window of at most 48 hours and known evidence logs.")
        _check_segment(data.covering or {}, DIMENSIONS)
        return data

    node_id = getattr(data, "node", None)
    node = graph.node(node_id) if node_id is not None else None
    imported_clock = source_clocks.get(node.source) if source_clocks and node else None
    if imported_clock is not None:
        if name not in ("get_series", "segment_search", "placebo_test"):
            raise ValueError("This check is unavailable for daily imported metrics.")
        as_of, latest_hour = imported_clock

    raw_window = Window.model_validate(data.model_dump(include={"window"})["window"])
    window = utc_window(raw_window)
    data = data.model_copy(update={"window": window})
    if (
        any(ts != ts.replace(minute=0, second=0, microsecond=0) for ts in (window.start, window.end))
        or not window.start <= window.end <= min(as_of, latest_hour)
        or window.end - window.start >= 48 * HOUR
    ):
        raise ValueError("Use a visible window of 1 to 48 whole data hours.")

    if node is not None and node.kind is NodeKind.DERIVED:
        raise ValueError("This metric cannot be queried by the toolbox.")
    segment = getattr(data, "segment", {})
    if imported_clock is not None and node is not None:
        if any(dim not in node.dims or len(value) > 2048 or not value.isprintable() for dim, value in segment.items()):
            raise ValueError("Choose a valid provider dimension.")
    else:
        _check_segment(segment, node.dims if node else DIMENSIONS)
    if isinstance(data, DecomposeFormulaInput):
        for factor in product_factors(graph, data.node) or ():
            _check_segment(data.segment, graph.node(factor).dims)
    if isinstance(data, CheckIdentitiesInput):
        for edge in graph.edges:
            if edge.kind == "formula" and len(edge.sources) == 1 and edge.expr == edge.sources[0]:
                for member in (edge.target, edge.sources[0]):
                    _check_segment(data.segment, graph.node(member).dims)
    if isinstance(data, CheckFreshnessInput) and (
        not data.tables or set(data.tables) - _FACT_NAMES or len(set(data.tables)) != len(data.tables)
    ):
        raise ValueError("Choose distinct fact tables.")
    if isinstance(data, MixRateSplitInput) and (
        node is None or node.kind is not NodeKind.RATIO or data.dim not in node.dims
    ):
        raise ValueError("Mix and rate require a ratio and one of its dimensions.")
    if (
        isinstance(data, SegmentSearchInput)
        and data.dims is not None
        and (node is None or sorted(data.dims) != sorted(node.dims))
    ):
        raise ValueError("Segment search requires all dimensions of the metric.")
    if isinstance(data, PlaceboTestInput) and not 1 <= data.weeks <= 8:
        raise ValueError("Placebo history must cover 1 to 8 weeks.")
    if isinstance(data, HoldoutCheckInput):
        event = data.event.model_copy(update={"ts": utc(data.event.ts)})
        stored = events.get((event.log, event.ref))
        if (
            stored is None
            or stored != event
            or stored.ts > as_of
            or node is None
            or not covers(stored.scope, data.segment, node.dims)
            or any(set(values) - set(DIMENSIONS.get(dim, ())) for dim, values in stored.scope.items())
        ):
            raise ValueError("The holdout requires the exact event previously observed in this run.")
        data = data.model_copy(update={"event": stored})
    return data
