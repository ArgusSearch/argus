"""Stage-2 tools on top of the Stage-1 toolbox (`argus.investigator.tools.Toolbox`).

Added C6 tools: `placebo_test`, `mix_rate_split`, `get_series`, `counterfactual_impact` and a holdout
check that falls back to a control group when the event's scope leaves nothing to hold out.
`run(name, payload)` executes any implemented C6 tool from its typed input model, which is the only
way a planner (or an LLM behind it) can make Argus query data. No tool accepts free SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from argus.contracts.findings import EvidenceRef, Segment, Window
from argus.contracts.graph import Graph, NodeKind
from argus.contracts.tools import (
    TOOL_MODELS,
    CheckFreshnessInput,
    CheckIdentitiesInput,
    CounterfactualImpactInput,
    CounterfactualImpactOutput,
    DecomposeFormulaInput,
    DecomposeFormulaOutput,
    GetSeriesInput,
    GetSeriesOutput,
    HoldoutCheckInput,
    HoldoutCheckOutput,
    ListEventsInput,
    MixRateSplitInput,
    MixRateSplitOutput,
    PlaceboTestInput,
    PlaceboTestOutput,
    SegmentSearchInput,
    SeriesPoint,
    ToolOutput,
)
from argus.contracts.world import DIMENSIONS
from argus.decompose.lmdi import lmdi
from argus.decompose.mix_rate import mix_rate_split
from argus.decompose.segments import Cell
from argus.investigate.walk import FactorView
from argus.investigate.weekly import WeekStat, fetch_weekly, week_stat
from argus.investigator.tools import HOLDOUT_Z, Toolbox
from argus.semantic.compile import hourly_sql, measures_window_sql, quote, scope_where, segment_where, window_hours
from argus.semantic.runner import Runner, sql_ts

HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
PLACEBO_Z = 3.0
PLACEBO_WEEKS = 8
FLAT_Z = 2.0
CONTROL_NORMAL_REL = 0.25  # a control group within a quarter of the anomaly's relative change counts as normal
IMPACT_NODE = "orders"


@dataclass(frozen=True)
class ProductSplit:
    """Exact LMDI split of a node's change over the factors of one product, with each factor's z."""

    node: str
    factors: list[FactorView]
    change: float
    residual: float
    rel_change: float
    receipts: list[str]


class ToolUnavailable(RuntimeError):
    """The tool is part of C6 but not implemented by this toolbox (for example lag_test, lane G)."""


def neighbours_where(segment: Segment) -> str | None:
    """Rows that match the segment on all but exactly one dimension (the segment's direct neighbours)."""
    if not segment:
        return None
    items = sorted(segment.items())
    if len(items) == 1:
        dim, value = items[0]
        return f"{dim} <> {quote(value)}"
    clauses = []
    for i, (dim, value) in enumerate(items):
        same = [f"{d} = {quote(v)}" for j, (d, v) in enumerate(items) if j != i]
        clauses.append("(" + " AND ".join([*same, f"{dim} <> {quote(value)}"]) + ")")
    return " OR ".join(clauses)


def sign_of(value: float) -> float:
    return 1.0 if value >= 0 else -1.0


class StageTwoToolbox(Toolbox):
    def __init__(self, graph: Graph, runner: Runner, as_of: datetime):
        super().__init__(graph, runner, as_of)
        self._cells: dict[tuple[str, datetime, datetime, str | None, str], tuple[list[Cell], str]] = {}

    # ------------------------------------------------------------------ shared building blocks
    def cells(self, node_id: str, window: Window, dim: str | None, where: str) -> tuple[list[Cell], str]:
        """Memoised: the mix check, the segment search and the holdouts ask for the same cells."""
        key = (node_id, window.start, window.end, dim, where)
        if key not in self._cells:
            self._cells[key] = super().cells(node_id, window, dim, where)
        return self._cells[key]

    def factor_stats(
        self, factors: list[str], segment: Segment, window: Window, weeks: int = 4
    ) -> tuple[dict[str, WeekStat], list[str]]:
        """Week-spread-aware z of every LMDI factor in the window (one query per fact view)."""
        series = fetch_weekly(
            self.graph,
            self.runner,
            self.as_of,
            factors,
            window,
            segment_where(segment),
            weeks=weeks,
            purpose="LMDI factors week by week: how unusual is each factor's move?",
        )
        stats = {f: s for f, s in ((f, week_stat(series[f])) for f in factors) if s is not None}
        receipts = sorted({r for s in series.values() for r in s.receipts}, key=lambda r: int(r[1:]))
        return stats, receipts

    def decompose_product(
        self, node_id: str, factors: list[str], segment: Segment, window: Window, weeks: int = 4
    ) -> ProductSplit | None:
        """LMDI over any exact product of the node (formula edge or ratio identity), from one week-by-week
        query per fact view, so the contributions and the factors' significance share their receipts.
        Baseline = mean of the same hours in `weeks` earlier weeks (ratios pooled), as in Stage 1."""
        series = fetch_weekly(
            self.graph,
            self.runner,
            self.as_of,
            [node_id, *factors],
            window,
            segment_where(segment),
            weeks=weeks,
            purpose=f"exact split of {node_id} into {' x '.join(factors)}, week by week",
        )
        stats: dict[str, WeekStat] = {}
        for n in [node_id, *factors]:
            stat = week_stat(series[n])
            if stat is None or stat.baseline <= 0 or stat.current <= 0:
                return None  # no logarithm for zero or missing weeks: the split is not defined
            stats[n] = stat
        contrib, _, _ = lmdi({f: stats[f].baseline for f in factors}, {f: stats[f].current for f in factors})
        change = stats[node_id].current - stats[node_id].baseline
        views = [
            FactorView(
                node=f,
                contribution=contrib[f],
                share=contrib[f] / change if change else 0.0,
                z=stats[f].z,
                rel_change=stats[f].rel_change,
            )
            for f in sorted(factors, key=lambda k: -abs(contrib[k]))
        ]
        receipts = sorted({r for s in series.values() for r in s.receipts}, key=lambda r: int(r[1:]))
        return ProductSplit(
            node=node_id,
            factors=views,
            change=change,
            residual=change - sum(contrib.values()),
            rel_change=stats[node_id].rel_change,
            receipts=receipts,
        )

    # ------------------------------------------------------------------ placebo
    def placebo_test(
        self, node_id: str, segment: Segment, window: Window, weeks: int = PLACEBO_WEEKS, direction: float | None = None
    ) -> tuple[PlaceboTestOutput, dict[str, Any]]:
        """Would the same check fire on the same hours of earlier weeks?

        Each earlier week plays the current one against the mean of the other earlier weeks (the current
        week is never part of a placebo baseline). A hit is an earlier week that deviates in the direction
        of the real change at least as strongly as the real window does (capped at |z| >= 3), so zero hits
        means the real deviation is larger than anything the same hours showed before.
        """
        node = self.graph.node(node_id)
        series = fetch_weekly(
            self.graph,
            self.runner,
            self.as_of,
            [node_id],
            window,
            segment_where(segment, node.dims),
            weeks=weeks,
            purpose=f"placebo: {node_id} in the same hours of up to {weeks} earlier weeks",
        )[node_id]
        earlier = series.earlier()
        actual = week_stat(series, 0, earlier)
        sign = direction if direction is not None else sign_of(actual.z if actual else 0.0)
        threshold = min(PLACEBO_Z, abs(actual.z)) if actual else PLACEBO_Z
        per_week = []
        hits = 0
        for week in earlier:
            stat = week_stat(series, week, [k for k in earlier if k != week])
            if stat is None:
                continue
            hit = abs(stat.z) >= threshold and stat.z * sign > 0
            hits += hit
            per_week.append({"weeks_back": week, "rel_change": round(stat.rel_change, 4), "z": round(stat.z, 2)})
        tested = len(per_week)
        actual_text = f"the real window: {actual.rel_change:+.1%} (z {actual.z:+.1f}); " if actual else ""
        summary = f"{actual_text}{hits} of {tested} earlier weeks deviate as much (|z| >= {threshold:.1f}) the same way"
        detail = {
            "actual": {"rel_change": round(actual.rel_change, 4), "z": round(actual.z, 2)} if actual else None,
            "threshold_z": round(threshold, 2),
            "weeks": per_week,
        }
        return PlaceboTestOutput(summary=summary, receipts=list(series.receipts), hits=hits, weeks=tested), detail

    # ------------------------------------------------------------------ mix vs rate
    def mix_rate(self, node_id: str, dim: str, segment: Segment, window: Window) -> MixRateSplitOutput:
        node = self.graph.node(node_id)
        if node.kind is not NodeKind.RATIO:
            raise ValueError(f"mix_rate_split needs a ratio node, {node_id} is {node.kind.value}")
        cells, rid = self.cells(node_id, window, dim, segment_where(segment, node.dims))
        live = [c for c in cells if c.base_den and c.cur_den]
        if not live:
            return MixRateSplitOutput(
                summary=f"{node_id} by {dim}: no volume", receipts=[rid], change=0.0, mix=0.0, rate=0.0, rates_flat=True
            )
        split = mix_rate_split(
            {c.value: c.base for c in live},
            {c.value: c.base_den or 0.0 for c in live},
            {c.value: c.cur for c in live},
            {c.value: c.cur_den or 0.0 for c in live},
        )
        flat = all(abs(c.z) < FLAT_Z for c in live)
        moved = max(live, key=lambda c: abs(c.z))
        summary = (
            f"{node_id} by {dim}: change {split.change:+.5f} = mix {split.mix:+.5f} + rate {split.rate:+.5f}; "
            + ("every segment's own rate is flat" if flat else f"{moved.value} rate moved (z {moved.z:+.1f})")
        )
        return MixRateSplitOutput(
            summary=summary,
            receipts=[rid],
            change=split.change,
            mix=split.mix,
            rate=split.rate,
            rates_flat=flat,
        )

    # ------------------------------------------------------------------ holdout with control fallback
    def control_check(
        self, event: EvidenceRef, node_id: str, segment: Segment, window: Window, anomaly_rel: float
    ) -> HoldoutCheckOutput:
        """The event applies only inside the segment, so test the converse: where it did not apply,
        the node must be normal. Uses the part of the segment outside the event's scope when the event is
        narrower, otherwise the segment's direct neighbours (all dims equal but one)."""
        node = self.graph.node(node_id)
        extra = {d: vals for d, vals in event.scope.items() if d not in segment and d in node.dims}
        if extra:
            where: str | None = f"({segment_where(segment, node.dims)}) AND NOT ({scope_where(extra)})"
            described = "the part of the segment outside the event's scope"
        else:
            where = neighbours_where(segment)
            described = "the neighbouring segments the event did not touch"
        if where is None:
            return HoldoutCheckOutput(
                summary="no control group: the event covers the whole business",
                holdout={},
                rel_change=None,
                z=None,
                result="not_applicable",
            )
        cells, rid = self.cells(node_id, window, None, where)
        cell = cells[0] if cells else None
        if cell is None or not cell.volume:
            return HoldoutCheckOutput(
                summary=f"no volume in {described}",
                receipts=[rid],
                holdout={"kind": "control", "where": where},
                rel_change=None,
                z=None,
                result="not_applicable",
            )
        rel, z = cell.rel_change, cell.z
        normal = abs(z) < HOLDOUT_Z or abs(rel) < CONTROL_NORMAL_REL * abs(anomaly_rel)
        result, text = (
            ("consistent", "control normal, the change sits where the event applies")
            if normal
            else ("inconclusive", "the change also appears where the event does not apply")
        )
        return HoldoutCheckOutput(
            summary=f"{text}: {described} {rel:+.1%} (z {z:+.1f}) vs {anomaly_rel:+.1%} inside",
            receipts=[rid],
            holdout={"kind": "control", "description": described, "where": where},
            rel_change=round(rel, 4),
            z=round(z, 2),
            result=result,
        )

    def holdout_or_control(
        self, event: EvidenceRef, node_id: str, segment: Segment, window: Window, anomaly_rel: float
    ) -> HoldoutCheckOutput:
        """Stage-1 holdout; when it has nothing to hold out (`not_applicable`), the control check decides.
        A `not_applicable` holdout is never counted as support on its own."""
        out = self.holdout_check(event, node_id, segment, window, anomaly_rel)
        if out.result != "not_applicable":
            return out
        return self.control_check(event, node_id, segment, window, anomaly_rel)

    def segment_rel(self, node_id: str, segment: Segment, window: Window) -> tuple[Cell, str]:
        node = self.graph.node(node_id)
        cells, rid = self.cells(node_id, window, None, segment_where(segment, node.dims))
        return cells[0], rid

    # ------------------------------------------------------------------ typed dispatch (planner path)
    def run(self, name: str, payload: dict[str, Any]) -> ToolOutput:
        """Validate `payload` against the tool's C6 input model, run it, return its C6 output model."""
        if name not in TOOL_MODELS:
            raise KeyError(f"unknown tool {name!r}; C6 tools: {sorted(TOOL_MODELS)}")
        in_model, out_model = TOOL_MODELS[name]
        data = in_model.model_validate(payload)
        handler = getattr(self, f"_run_{name}", None)
        if handler is None:
            raise ToolUnavailable(f"{name} is not implemented by the investigator toolbox")
        out = handler(data)
        assert isinstance(out, out_model) and isinstance(out, ToolOutput)
        return out

    def _run_get_series(self, inp: GetSeriesInput) -> GetSeriesOutput:
        node = self.graph.node(inp.node)
        cond = " OR ".join(
            f"ts BETWEEN {sql_ts(inp.window.start - k * WEEK)} AND {sql_ts(inp.window.end - k * WEEK)}"
            for k in range(5)
        )
        rows, receipt = self.runner.query(
            hourly_sql(self.graph, inp.node, cond, inp.segment), self.as_of, purpose=f"hourly {inp.node}"
        )

        def value(r: dict[str, Any]) -> float | None:
            if node.kind is NodeKind.RATIO:
                return float(r["num"] or 0) / float(r["den"]) if r["den"] else None
            return float(r["value"] or 0)

        by_ts = {r["ts"]: value(r) for r in rows}
        points = []
        hour = inp.window.start
        while hour <= inp.window.end:
            base = [by_ts.get(hour - k * WEEK) for k in range(1, 5)]
            known = [b for b in base if b is not None]
            points.append(
                SeriesPoint(hour=hour, value=by_ts.get(hour), expected=sum(known) / len(known) if known else None)
            )
            hour += HOUR
        return GetSeriesOutput(summary=f"{len(points)} hours of {inp.node}", receipts=[receipt.id], points=points)

    def _run_check_freshness(self, inp: CheckFreshnessInput) -> ToolOutput:
        return self.check_freshness(inp.tables, inp.window)

    def _run_check_identities(self, inp: CheckIdentitiesInput) -> ToolOutput:
        return self.check_identities(inp.window, inp.segment)

    def _run_decompose_formula(self, inp: DecomposeFormulaInput) -> DecomposeFormulaOutput:
        out = self.decompose_formula(inp.node, inp.segment, inp.window)
        if out is None:
            return DecomposeFormulaOutput(
                summary=f"{inp.node} has no product formula", node=inp.node, factors=[], contributions=[], residual=0.0
            )
        return out

    def _run_mix_rate_split(self, inp: MixRateSplitInput) -> MixRateSplitOutput:
        return self.mix_rate(inp.node, inp.dim, inp.segment, inp.window)

    def _run_segment_search(self, inp: SegmentSearchInput) -> ToolOutput:
        out = self.segment_search(inp.node, inp.window, inp.segment).output
        if inp.dims is not None:
            out = out.model_copy(update={"summary": out.summary + " (searched every dimension of the node)"})
        return out

    def _run_list_events(self, inp: ListEventsInput) -> ToolOutput:
        return self.list_events(inp.start, inp.end, logs=inp.logs, covering=inp.covering, node_dims=list(DIMENSIONS))

    def _run_holdout_check(self, inp: HoldoutCheckInput) -> HoldoutCheckOutput:
        cell, _ = self.segment_rel(inp.node, inp.segment, inp.window)
        return self.holdout_or_control(inp.event, inp.node, inp.segment, inp.window, cell.rel_change)

    def _run_placebo_test(self, inp: PlaceboTestInput) -> PlaceboTestOutput:
        out, _ = self.placebo_test(inp.node, inp.segment, inp.window, inp.weeks)
        return out

    def _run_counterfactual_impact(self, inp: CounterfactualImpactInput) -> CounterfactualImpactOutput:
        node = self.graph.node(inp.node)
        cell, rid = self.segment_rel(inp.node, inp.segment, inp.window)
        hours = window_hours(inp.window)
        lost = cell.deviation / hours
        counted = self.graph.node(node.numerator) if node.kind is NodeKind.RATIO and node.numerator else node
        receipts = [rid]
        if counted.id in (IMPACT_NODE, "payment_successes"):
            orders = self.graph.node(IMPACT_NODE)
            oseg = {d: v for d, v in inp.segment.items() if d in orders.dims}
            rows, receipt = self.runner.query(
                measures_window_sql("fact_orders_hourly", ["orders", "gmv"], inp.window, segment_where(oseg)),
                self.as_of,
                purpose="AOV for the EUR impact",
            )
            receipts.append(receipt.id)
            base_orders = float(rows[0]["base_orders"] or 0)
            gmv_per_hour = lost * (float(rows[0]["base_gmv"] or 0) / base_orders if base_orders else 0.0)
        else:
            gmv_per_hour = lost if counted.unit == "eur" else 0.0
        return CounterfactualImpactOutput(
            summary=f"{lost:+.1f} {counted.id}/h, EUR {gmv_per_hour:+,.0f}/h against the expectation",
            receipts=receipts,
            per_hour=lost,
            so_far=lost * hours,
            gmv_eur_per_hour=gmv_per_hour,
        )
