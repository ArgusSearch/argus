"""Hourly series of graph nodes, cached per (fact view, group-by dims).

The watcher needs about five weeks of history for every series it scores (four baseline weeks plus a
week of residuals for the noise scale). Fetching that every tick would be wasteful, so each
(view, dims) pair is fetched once and then extended with the new hours only. An hour is cached for good
once its table was complete when it was fetched (it can no longer change); unsettled hours are fetched
again on the next tick, so a late backfill is picked up automatically.

The cache keeps wide frames (one column per slice) so a tick only pivots the hours it fetched.
All queries run through `Runner.fetch` with `as_of` pinned, i.e. without receipts: these are monitoring
internals. When the watcher shows a number to a human (an anomaly), it re-runs a small receipt query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from argus.contracts.graph import EdgeKind, Graph, NodeKind
from argus.contracts.world import table
from argus.semantic.runner import Runner, sql_ts

HOUR = timedelta(hours=1)
SliceKey = str
"""Slice label: the dim values joined by "|" in dims order; "" is the whole business."""
SEP = "|"


@dataclass
class _Cached:
    """Wide frames (index ts, one column per slice) of every measure of one (view, dims) pair."""

    wide: dict[str, pd.DataFrame]
    first: datetime
    settled_until: datetime | None
    fetched: tuple[datetime, datetime] | None = None  # (as_of, end) of the last fetch


@dataclass(frozen=True)
class NodeSeries:
    """Wide hourly arrays of one node grouped by `dims`: one column per slice, one row per hour."""

    node: str
    dims: tuple[str, ...]
    hours: pd.DatetimeIndex
    num: pd.DataFrame
    den: pd.DataFrame | None

    def slices(self) -> list[SliceKey]:
        return list(self.num.columns)

    def segment(self, key: SliceKey) -> dict[str, str]:
        return dict(zip(self.dims, key.split(SEP), strict=True)) if self.dims else {}

    def arrays(self, key: SliceKey) -> tuple[np.ndarray, np.ndarray | None]:
        num = self.num[key].to_numpy(dtype=float)
        den = None if self.den is None else self.den[key].to_numpy(dtype=float)
        return num, den


def hour_range(start: datetime, end: datetime) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq="h")


class SeriesStore:
    """Incremental cache of hourly measure sums per (fact view, dims)."""

    def __init__(self, runner: Runner, graph: Graph):
        self.runner = runner
        self.graph = graph
        self._cache: dict[tuple[str, tuple[str, ...]], _Cached] = {}
        self.queries = 0

    def _fetch(self, view: str, dims: tuple[str, ...], start: datetime, end: datetime, as_of: datetime) -> pd.DataFrame:
        spec = table(view)
        keys = ", ".join(["ts", *dims])
        sums = ", ".join(f"SUM({m}) AS {m}" for m in spec.measures)
        sql = f"SELECT {keys}, {sums} FROM {view} WHERE ts BETWEEN {sql_ts(start)} AND {sql_ts(end)} GROUP BY {keys}"
        self.queries += 1
        rows = self.runner.fetch(sql, as_of)
        frame = pd.DataFrame(rows, columns=["ts", *dims, *spec.measures])
        frame["ts"] = pd.to_datetime(frame["ts"])
        for m in spec.measures:
            frame[m] = frame[m].astype(float)
        return frame

    @staticmethod
    def _pivot(frame: pd.DataFrame, dims: tuple[str, ...], measures: list[str]) -> dict[str, pd.DataFrame]:
        if dims:
            labels = frame[dims[0]].astype(str)
            for dim in dims[1:]:
                labels = labels + SEP + frame[dim].astype(str)
            grouped = frame.assign(_slice=labels).groupby(["ts", "_slice"])[measures].sum()
            wide = grouped.unstack("_slice")
            out = {}
            for m in measures:
                part = wide[m] if len(wide) else pd.DataFrame(index=pd.DatetimeIndex([], name="ts"))
                part.columns = [str(c) for c in part.columns]
                out[m] = part
            return out
        grouped = frame.groupby("ts")[measures].sum()
        return {m: grouped[[m]].set_axis([""], axis=1) for m in measures}

    def _ensure(
        self, view: str, dims: tuple[str, ...], start: datetime, end: datetime, as_of: datetime, settled: datetime
    ) -> _Cached:
        """Make the cache of (view, dims) cover [start, end] as seen at `as_of`, fetching only what is new."""
        measures = table(view).measures
        key = (view, dims)
        cached = self._cache.get(key)
        if cached is None or start < cached.first:
            fresh = self._fetch(view, dims, start, end, as_of)
            cached = _Cached(wide=self._pivot(fresh, dims, measures), first=start, settled_until=None)
            self._cache[key] = cached
        elif cached.fetched is None or cached.fetched[0] != as_of or cached.fetched[1] < end:
            fetch_from = cached.first if cached.settled_until is None else cached.settled_until + HOUR
            if fetch_from <= end:
                fresh_wide = self._pivot(self._fetch(view, dims, fetch_from, end, as_of), dims, measures)
                cut = pd.Timestamp(fetch_from)
                for m in measures:
                    old = cached.wide[m]
                    cached.wide[m] = pd.concat([old[old.index < cut], fresh_wide[m]])
        cached.settled_until = min(end, settled)
        cached.fetched = (as_of, end)
        return cached

    def _wide(
        self,
        view: str,
        measure: str,
        dims: tuple[str, ...],
        hours: pd.DatetimeIndex,
        as_of: datetime,
        settled: dict[str, datetime],
    ) -> pd.DataFrame:
        start, end = hours[0].to_pydatetime(), hours[-1].to_pydatetime()
        cached = self._ensure(view, dims, start, end, as_of, settled.get(view, end))
        return cached.wide[measure].reindex(hours)

    def node_series(
        self,
        node_id: str,
        dims: tuple[str, ...],
        start: datetime,
        end: datetime,
        as_of: datetime,
        settled: dict[str, datetime],
    ) -> NodeSeries:
        """Hourly series of a node for [start, end], one column per slice of `dims` (one column if no dims)."""
        node = self.graph.node(node_id)
        hours = hour_range(start, end)
        if node.kind is NodeKind.ADDITIVE:
            assert node.table and node.measure
            num = self._wide(node.table, node.measure, dims, hours, as_of, settled)
            return NodeSeries(node_id, dims, hours, num, None)
        if node.kind is NodeKind.RATIO:
            num_node = self.graph.node(node.numerator or "")
            den_node = self.graph.node(node.denominator or "")
            assert num_node.table and num_node.measure and den_node.table and den_node.measure
            num = self._wide(num_node.table, num_node.measure, dims, hours, as_of, settled)
            den = self._wide(den_node.table, den_node.measure, dims, hours, as_of, settled)
            cols = [c for c in num.columns if c in set(den.columns)]
            return NodeSeries(node_id, dims, hours, num[cols], den[cols])
        raise NotImplementedError(f"derived node {node_id} is not watched yet")


def source_tables(graph: Graph, node_id: str) -> list[str]:
    """Fact views a node reads (both sides of a ratio)."""
    node = graph.node(node_id)
    if node.kind is NodeKind.ADDITIVE:
        return [node.table] if node.table else []
    if node.kind is NodeKind.RATIO:
        out = {graph.node(node.numerator or "").table, graph.node(node.denominator or "").table}
        return sorted(t for t in out if t)
    return []


def count_driver(graph: Graph, node_id: str) -> str | None:
    """The event count behind an additive node: itself for counts, the count factor of its product formula
    for amounts (gmv = orders * aov gives orders), None when the graph does not say."""
    node = graph.node(node_id)
    if node.kind is not NodeKind.ADDITIVE:
        return None
    if node.unit == "count":
        return node.id
    for edge in graph.edges_into(node_id, EdgeKind.FORMULA):
        if edge.expr != " * ".join(edge.sources):
            continue
        for src in edge.sources:
            other = graph.node(src)
            if other.kind is NodeKind.ADDITIVE and other.unit == "count" and other.table == node.table:
                return other.id
    return None


def noise_drivers(graph: Graph, node_id: str) -> list[str] | None:
    """Counts whose Poisson noise adds up to the noise of ln(node), or None when unknown.

    A ratio whose numerator and denominator share one driver (aov = gmv / orders) keeps a single entry:
    the two sides move together, so their counting noise does not add up.
    """
    node = graph.node(node_id)
    if node.kind is NodeKind.ADDITIVE:
        driver = count_driver(graph, node_id)
        return [driver] if driver else None
    if node.kind is NodeKind.RATIO:
        drivers = [count_driver(graph, node.numerator or ""), count_driver(graph, node.denominator or "")]
        if any(d is None for d in drivers):
            return None
        return sorted({d for d in drivers if d})
    return None
