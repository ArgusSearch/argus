"""Week-by-week values of a node: the investigation window and the same hours in each earlier week.

The fixed opening compares the window with the *mean* of the same hours in the four previous weeks.
The Stage-2 checks need the weeks one by one:

* their spread says how unusual a change is (significance-aware factor choice in the LMDI walk);
* every earlier week can play the current one (placebo test).

One query per fact view, grouped by week offset, so every number keeps its receipt. A week only counts
when every hour of the shifted window is present (weeks before the start of history drop out).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from argus.contracts.findings import Window
from argus.contracts.graph import Graph, NodeKind
from argus.decompose.segments import OVERDISPERSION
from argus.semantic.compile import parts, window_condition, window_hours
from argus.semantic.runner import Runner

WEEK = timedelta(days=7)


@dataclass(frozen=True)
class WeekValue:
    """Window totals of one week: the value (additive) or numerator and denominator (ratio)."""

    week: int
    num: float
    den: float | None = None

    @property
    def value(self) -> float | None:
        if self.den is None:
            return self.num
        return self.num / self.den if self.den else None


@dataclass(frozen=True)
class WeeklySeries:
    """`weeks[0]` is the window itself, `weeks[k]` the same hours k weeks earlier (complete weeks only)."""

    node: str
    is_ratio: bool
    is_share: bool
    weeks: dict[int, WeekValue]
    receipts: tuple[str, ...]

    def earlier(self) -> list[int]:
        return sorted(k for k in self.weeks if k > 0)


@dataclass(frozen=True)
class WeekStat:
    """Current vs baseline weeks: pooled baseline, relative change and a z that respects the week spread."""

    current: float
    baseline: float
    rel_change: float
    z: float
    sd: float
    baseline_weeks: int


def weekly_sql(table: str, measures: list[str], window: Window, where: str = "TRUE", weeks: int = 4) -> str:
    """Totals of `measures` per week offset 0..weeks, plus the number of distinct hours seen in each week."""
    conditions = [window_condition(window, WEEK * k) for k in range(weeks + 1)]
    cases = " ".join(f"WHEN {c} THEN {k}" for k, c in enumerate(conditions))
    sums = ", ".join(f"SUM({m}) AS {m}" for m in measures)
    return (
        f"SELECT CASE {cases} END AS week, COUNT(DISTINCT ts) AS hours, {sums} FROM {table} "
        f"WHERE ({where}) AND ({' OR '.join(conditions)}) GROUP BY week ORDER BY week"
    )


def fetch_weekly(
    graph: Graph,
    runner: Runner,
    as_of: datetime,
    node_ids: list[str],
    window: Window,
    where: str = "TRUE",
    weeks: int = 4,
    purpose: str = "",
) -> dict[str, WeeklySeries]:
    """Weekly series of several nodes from one query per fact view. `where` must be valid on every view."""
    needed: dict[str, set[str]] = defaultdict(set)
    for node_id in node_ids:
        for part in parts(graph, node_id):
            assert part.node.table and part.node.measure
            needed[part.node.table].add(part.node.measure)
    hours = window_hours(window)
    totals: dict[int, dict[str, float]] = defaultdict(dict)
    complete: set[int] | None = None
    receipts: list[str] = []
    for table, measures in sorted(needed.items()):
        ms = sorted(measures)
        rows, receipt = runner.query(
            weekly_sql(table, ms, window, where, weeks), as_of, purpose=purpose or f"week-by-week totals from {table}"
        )
        receipts.append(receipt.id)
        seen = set()
        for r in rows:
            if r["week"] is None or int(r["hours"]) != hours:
                continue
            k = int(r["week"])
            seen.add(k)
            for m in ms:
                totals[k][m] = float(r[m] or 0)
        complete = seen if complete is None else complete & seen
    out: dict[str, WeeklySeries] = {}
    for node_id in node_ids:
        node = graph.node(node_id)
        ps = parts(graph, node_id)
        values: dict[int, WeekValue] = {}
        for k in sorted(complete or set()):
            if len(ps) == 1:
                values[k] = WeekValue(k, totals[k][ps[0].node.measure or ""])
            else:
                values[k] = WeekValue(k, totals[k][ps[0].node.measure or ""], totals[k][ps[1].node.measure or ""])
        out[node_id] = WeeklySeries(
            node=node_id,
            is_ratio=node.kind is NodeKind.RATIO,
            is_share=node.unit == "share",
            weeks=values,
            receipts=tuple(receipts),
        )
    return out


def week_stat(series: WeeklySeries, current: int = 0, baseline: list[int] | None = None) -> WeekStat | None:
    """Compare week `current` with the pooled `baseline` weeks (default: every earlier week).

    The scale is the larger of the week-to-week spread and the sampling floor (Poisson with the same
    overdispersion floor as the segment search for counts, binomial for shares), so a factor only looks
    significant when it moved more than it normally does between weeks.
    """
    base_ids = [k for k in (baseline if baseline is not None else series.earlier()) if k != current]
    if current not in series.weeks or len(base_ids) < 2:
        return None
    cur = series.weeks[current]
    base = [series.weeks[k] for k in base_ids if k in series.weeks]
    if len(base) < 2:
        return None
    if series.is_ratio:
        num0 = sum(b.num for b in base)
        den0 = sum(b.den or 0 for b in base)
        if not den0 or not cur.den:
            return None
        x0, x1 = num0 / den0, cur.num / cur.den
        if series.is_share and 0 < x0 < 1:
            floor = math.sqrt(x0 * (1 - x0) * (1 / cur.den + 1 / den0))
        else:
            floor = abs(x0) * math.sqrt(1 / max(cur.num, 1.0) + 1 / max(cur.den, 1.0))
        per_week = [b.value for b in base if b.value is not None]
    else:
        x1 = cur.num
        per_week = [b.num for b in base]
        x0 = sum(per_week) / len(per_week)
        floor = math.sqrt(max(x0, 1.0) + (OVERDISPERSION * x0) ** 2)
    sd = max(_stdev(per_week), floor)
    rel = x1 / x0 - 1 if x0 else 0.0
    z = (x1 - x0) / sd if sd > 0 else 0.0
    return WeekStat(current=x1, baseline=x0, rel_change=rel, z=z, sd=sd, baseline_weeks=len(base))


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
