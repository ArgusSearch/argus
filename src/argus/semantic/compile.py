"""Compile graph nodes into SQL against the C1 views.

Each additive node is a SUM over one fact view. A ratio node is compiled as its numerator and its
denominator, each aggregated in its own table at the requested grain and only then joined, so a
ratio across tables with different grains can never fan out.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from argus.contracts.findings import Segment, Window
from argus.contracts.graph import Graph, Node, NodeKind
from argus.contracts.world import table
from argus.semantic.runner import sql_ts

WEEK = timedelta(days=7)
BASELINE_WEEKS = 4


@dataclass(frozen=True)
class Part:
    """One additive ingredient of a node: alias 'value' (additive) or 'num' / 'den' (ratio)."""

    alias: str
    node: Node


def parts(graph: Graph, node_id: str) -> list[Part]:
    node = graph.node(node_id)
    if node.kind is NodeKind.ADDITIVE:
        return [Part("value", node)]
    if node.kind is NodeKind.RATIO:
        assert node.numerator and node.denominator
        return [Part("num", graph.node(node.numerator)), Part("den", graph.node(node.denominator))]
    raise NotImplementedError(f"derived node {node_id}: compile its expr over additive nodes (lane G)")


def tables_of(graph: Graph, node_id: str) -> list[str]:
    return sorted({p.node.table for p in parts(graph, node_id) if p.node.table})


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def segment_where(segment: Segment, allowed: list[str] | None = None) -> str:
    if not segment:
        return "TRUE"
    if allowed is not None:
        missing = [d for d in segment if d not in allowed]
        if missing:
            raise ValueError(f"segment dims {missing} are not available (allowed: {allowed})")
    return " AND ".join(f"{d} = {quote(v)}" for d, v in sorted(segment.items()))


def scope_where(scope: dict[str, list[str]]) -> str:
    if not scope:
        return "TRUE"
    return " AND ".join(f"{d} IN ({', '.join(quote(v) for v in sorted(vals))})" for d, vals in sorted(scope.items()))


def window_condition(window: Window, shift: timedelta = timedelta(0)) -> str:
    return f"ts BETWEEN {sql_ts(window.start - shift)} AND {sql_ts(window.end - shift)}"


def baseline_condition(window: Window, weeks: int = BASELINE_WEEKS) -> str:
    return "(" + " OR ".join(window_condition(window, WEEK * k) for k in range(1, weeks + 1)) + ")"


def window_hours(window: Window) -> int:
    return int((window.end - window.start) / timedelta(hours=1)) + 1


def _group(dims: list[str]) -> str:
    return f" GROUP BY {', '.join(dims)}" if dims else ""


def window_compare_sql(
    graph: Graph,
    node_id: str,
    window: Window,
    dims: list[str] | None = None,
    where: str = "TRUE",
    weeks: int = BASELINE_WEEKS,
) -> str:
    """Current window vs the mean of the same hours in the previous `weeks` weeks.

    Columns: the group-by `dims`, then `cur_<alias>` and `base_<alias>` for every part
    (`value` for additive nodes, `num` and `den` for ratios). Totals over the window, not per hour.
    """
    dims = list(dims or [])
    node = graph.node(node_id)
    bad = [d for d in dims if d not in node.dims]
    if bad:
        raise ValueError(f"{node_id} cannot be grouped by {bad}")
    by_table: dict[str, list[Part]] = defaultdict(list)
    for part in parts(graph, node_id):
        assert part.node.table
        by_table[part.node.table].append(part)

    cur, base = window_condition(window), baseline_condition(window, weeks)
    ctes, aliases = [], []
    for i, (tbl, tparts) in enumerate(sorted(by_table.items())):
        cols = []
        for p in tparts:
            cols.append(f"SUM(CASE WHEN {cur} THEN {p.node.measure} END) AS cur_{p.alias}")
            cols.append(f"SUM(CASE WHEN {base} THEN {p.node.measure} END) / {float(weeks)} AS base_{p.alias}")
            aliases += [f"cur_{p.alias}", f"base_{p.alias}"]
        select = ", ".join([*dims, *cols])
        ctes.append(f"t{i} AS (SELECT {select} FROM {tbl} WHERE ({where}) AND ({cur} OR {base}){_group(dims)})")
    joined = "t0"
    for i in range(1, len(ctes)):
        joined += f" JOIN t{i} USING ({', '.join(dims)})" if dims else f" CROSS JOIN t{i}"
    order = f" ORDER BY {', '.join(dims)}" if dims else ""
    return f"WITH {', '.join(ctes)}\nSELECT {', '.join([*dims, *aliases])} FROM {joined}{order}"


def hourly_sql(graph: Graph, node_id: str, ts_condition: str, segment: Segment | None = None) -> str:
    """Hourly series of a node's parts: columns ts, then `value` or `num`, `den`."""
    node = graph.node(node_id)
    where = segment_where(segment or {}, node.dims)
    by_table: dict[str, list[Part]] = defaultdict(list)
    for part in parts(graph, node_id):
        assert part.node.table
        by_table[part.node.table].append(part)
    ctes, aliases = [], []
    for i, (tbl, tparts) in enumerate(sorted(by_table.items())):
        cols = ", ".join(f"SUM({p.node.measure}) AS {p.alias}" for p in tparts)
        aliases += [p.alias for p in tparts]
        ctes.append(f"t{i} AS (SELECT ts, {cols} FROM {tbl} WHERE ({where}) AND ({ts_condition}) GROUP BY ts)")
    joined = "t0" + "".join(f" JOIN t{i} USING (ts)" for i in range(1, len(ctes)))
    return f"WITH {', '.join(ctes)}\nSELECT ts, {', '.join(aliases)} FROM {joined} ORDER BY ts"


def points_condition(hours: list[datetime]) -> str:
    return "ts IN (" + ", ".join(sql_ts(h) for h in sorted(hours)) + ")"


def render_node_sql(graph: Graph, node: Node) -> str | None:
    """The node in C2 form (for display), or None when C2 cannot express it without a fan-out."""
    if node.kind is NodeKind.ADDITIVE:
        dims = ", ".join(["ts", *node.dims])
        return f"SELECT {dims}, SUM({node.measure}) AS value\nFROM {node.table}\nGROUP BY ALL"
    if node.kind is NodeKind.RATIO:
        num, den = graph.node(node.numerator or ""), graph.node(node.denominator or "")
        dims = ", ".join(["ts", *node.dims])
        value = f"SUM({num.measure})::DOUBLE / NULLIF(SUM({den.measure}), 0) AS value"
        if num.table == den.table:
            return f"SELECT {dims}, {value}\nFROM {num.table}\nGROUP BY ALL"
        assert num.table and den.table
        if table(num.table).grain == table(den.table).grain:
            keys = ", ".join(table(num.table).grain)
            return f"SELECT {dims}, {value}\nFROM {num.table} JOIN {den.table} USING ({keys})\nGROUP BY ALL"
    return None


def measures_window_sql(
    table_name: str, measures: list[str], window: Window, where: str = "TRUE", weeks: int = BASELINE_WEEKS
) -> str:
    """Window totals of several measures of one view: `cur_<m>` and `base_<m>` (mean of `weeks` prior weeks)."""
    cur, base = window_condition(window), baseline_condition(window, weeks)
    cols = []
    for m in measures:
        cols.append(f"SUM(CASE WHEN {cur} THEN {m} END) AS cur_{m}")
        cols.append(f"SUM(CASE WHEN {base} THEN {m} END) / {float(weeks)} AS base_{m}")
    return f"SELECT {', '.join(cols)} FROM {table_name} WHERE ({where}) AND ({cur} OR {base})"
