"""C6 tool implementations. Each tool runs fixed SQL through the runner (so every number has a receipt)
and returns the typed output model from `argus.contracts.tools`. No tool accepts free SQL."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from argus.contracts.findings import Contribution, EvidenceRef, Segment, TableFreshness, Window
from argus.contracts.graph import EdgeKind, Graph, NodeKind
from argus.contracts.tools import (
    CheckFreshnessOutput,
    CheckIdentitiesOutput,
    DecomposeFormulaOutput,
    HoldoutCheckOutput,
    IdentityCheck,
    ListEventsOutput,
    SegmentCell,
    SegmentSearchOutput,
)
from argus.contracts.world import EVIDENCE_LOGS
from argus.decompose.lmdi import lmdi, shares
from argus.decompose.segments import Cell, best_choice, should_descend
from argus.graph.store import product_factors
from argus.semantic.compile import (
    hourly_sql,
    measures_window_sql,
    parts,
    quote,
    scope_where,
    segment_where,
    window_compare_sql,
    window_hours,
)
from argus.semantic.runner import Runner, sql_ts
from argus.watcher.freshness import COMPLETE, completeness, freshness_sql

HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
ONSET_Z = 3.0  # stricter than the detector: extending the window backwards must not chase noise

IDENTITY_TOLERANCE = 0.005
HOLDOUT_Z = 2.0


def covers(scope: dict[str, list[str]], segment: Segment, node_dims: list[str]) -> bool:
    """Does an event's scope cover the segment? Scope dims must exist on the node, and wherever the
    segment fixes a dimension the scope must include that value. A missing scope dim means all values."""
    if any(d not in node_dims for d in scope):
        return False
    return all(segment[d] in vals for d, vals in scope.items() if d in segment)


def scope_inside(scope: dict[str, list[str]], segment: Segment) -> bool:
    """True when every row in the scope is also in the segment (the holdout would be empty)."""
    return all(d in scope and scope[d] == [v] for d, v in segment.items())


@dataclass
class SearchResult:
    output: SegmentSearchOutput
    final: Cell
    final_receipt: str
    total: Cell
    last_level: dict[str, list[Cell]]


class Toolbox:
    def __init__(self, graph: Graph, runner: Runner, as_of: datetime):
        self.graph = graph
        self.runner = runner
        self.as_of = as_of

    # ------------------------------------------------------------------ data before business
    def check_freshness(self, tables: list[str], window: Window, minimum: float = COMPLETE) -> CheckFreshnessOutput:
        found = completeness(self.runner, tables, window.start, window.end, self.as_of)
        hours = window_hours(window)
        rows = []
        for t in sorted(tables):
            vals = [min(1.0, v) for (name, _), v in found.items() if name == t]
            worst = min(vals) if len(vals) == hours else 0.0
            rows.append(
                TableFreshness(
                    table=t,
                    hour=window.end,
                    completeness=round(worst, 4),
                    status="ok" if worst >= minimum else "pending",
                )
            )
        # one receipt for the whole check, so the trail shows the SQL
        _, receipt = self.runner.query(
            freshness_sql(tables, window.start, window.end), self.as_of, purpose="freshness of the source tables"
        )
        ok = all(r.status == "ok" for r in rows)
        summary = (
            "all source tables complete"
            if ok
            else "incomplete: " + ", ".join(f"{r.table} {r.completeness:.0%}" for r in rows if r.status != "ok")
        )
        return CheckFreshnessOutput(summary=summary, receipts=[receipt.id], ok=ok, tables=rows)

    def check_identities(self, window: Window, segment: Segment | None = None) -> CheckIdentitiesOutput:
        checks, receipts = [], []
        for edge in self.graph.edges:
            if edge.kind is not EdgeKind.FORMULA or len(edge.sources) != 1 or edge.expr != edge.sources[0]:
                continue
            target, source = self.graph.node(edge.target), self.graph.node(edge.sources[0])
            values = {}
            for node in (target, source):
                assert node.table and node.measure
                where = segment_where(segment or {}, node.dims) if segment else "TRUE"
                rows, receipt = self.runner.query(
                    measures_window_sql(node.table, [node.measure], window, where),
                    self.as_of,
                    purpose=f"identity {edge.expr} = {edge.target}: {node.id} in the window",
                )
                receipts.append(receipt.id)
                values[node.id] = float(rows[0][f"cur_{node.measure}"] or 0)
            t, s = values[target.id], values[source.id]
            rel = abs(t - s) / abs(t) if t else (0.0 if s == 0 else 1.0)
            checks.append(
                IdentityCheck(
                    edge=edge.id,
                    expr=f"{edge.target} = {edge.expr}",
                    max_rel_residual=rel,
                    holds=rel <= IDENTITY_TOLERANCE,
                )
            )
        ok = all(c.holds for c in checks)
        summary = "identities hold" if ok else "broken: " + ", ".join(c.expr for c in checks if not c.holds)
        return CheckIdentitiesOutput(summary=summary, receipts=receipts, ok=ok, identities=checks)

    # ------------------------------------------------------------------ evidence
    def list_events(
        self,
        start: datetime,
        end: datetime,
        logs: list[str] | None = None,
        covering: Segment | None = None,
        node_dims: list[str] | None = None,
    ) -> ListEventsOutput:
        names = ", ".join(quote(log) for log in (logs or list(EVIDENCE_LOGS)))
        sql = (
            "SELECT log, id, ts, kind, scope, description FROM log_events "
            f"WHERE log IN ({names}) AND ts BETWEEN {sql_ts(start)} AND {sql_ts(end)} ORDER BY ts, id"
        )
        rows, receipt = self.runner.query(sql, self.as_of, purpose="log entries around the onset")
        events = []
        for r in rows:
            scope = json.loads(r["scope"]) if r["scope"] else {}
            ev = EvidenceRef(
                log=r["log"], ref=r["id"], ts=r["ts"], kind=r["kind"], description=r["description"], scope=scope
            )
            if covering is None or covers(scope, covering, node_dims or []):
                events.append(ev)
        summary = (
            f"{len(events)} of {len(rows)} log entries cover the segment"
            if covering is not None
            else f"{len(rows)} entries"
        )
        return ListEventsOutput(summary=summary, receipts=[receipt.id], events=events)

    # ------------------------------------------------------------------ localisation
    def cells(self, node_id: str, window: Window, dim: str | None, where: str) -> tuple[list[Cell], str]:
        node = self.graph.node(node_id)
        sql = window_compare_sql(self.graph, node_id, window, [dim] if dim else [], where)
        rows, receipt = self.runner.query(
            sql, self.as_of, purpose=f"{node_id} by {dim or 'total'}: window vs the same hours of 4 prior weeks"
        )
        out = []
        for r in rows:
            value = str(r[dim]) if dim else "total"
            if node.kind is NodeKind.RATIO:
                out.append(
                    Cell(
                        value,
                        float(r["cur_num"] or 0),
                        float(r["base_num"] or 0),
                        float(r["cur_den"] or 0),
                        float(r["base_den"] or 0),
                    )
                )
            else:
                out.append(Cell(value, float(r["cur_value"] or 0), float(r["base_value"] or 0)))
        return out, receipt.id

    def segment_search(self, node_id: str, window: Window, segment: Segment | None = None) -> SearchResult:
        node = self.graph.node(node_id)
        current: Segment = dict(segment or {})
        receipts: list[str] = []
        totals, rid = self.cells(node_id, window, None, segment_where(current, node.dims))
        receipts.append(rid)
        total = totals[0]
        final, final_receipt = total, rid
        path: list[SegmentCell] = []
        last_level: dict[str, list[Cell]] = {}
        remaining = [d for d in node.dims if d not in current]
        while remaining:
            level: dict[str, list[Cell]] = {}
            level_receipts: dict[str, str] = {}
            for dim in remaining:
                cells, rid = self.cells(node_id, window, dim, segment_where(current, node.dims))
                receipts.append(rid)
                level[dim] = cells
                level_receipts[dim] = rid
            last_level = level
            choice = best_choice(level)
            if choice is None or not should_descend(choice):
                break
            cell = choice.cells[0]
            current[choice.dim] = cell.value
            final, final_receipt = cell, level_receipts[choice.dim]
            ep_total = max(0.0, min(1.0, cell.deviation / total.deviation)) if total.deviation else 0.0
            path.append(
                SegmentCell(
                    segment=dict(current),
                    ep=round(ep_total, 4),
                    volume_share=round(choice.volume_share, 4),
                    rel_change=round(cell.rel_change, 4),
                )
            )
            remaining.remove(choice.dim)
        explained = path[-1].ep if path else 1.0
        where = " AND ".join(f"{k}={v}" for k, v in current.items()) or "the whole business"
        summary = f"{where} explains {explained:.0%} of the deviation ({final.rel_change:+.1%})"
        output = SegmentSearchOutput(
            summary=summary, receipts=receipts, segment=current, explained_share=explained, path=path
        )
        return SearchResult(output, final, final_receipt, total, last_level)

    def holdout_check(
        self, event: EvidenceRef, node_id: str, segment: Segment, window: Window, anomaly_rel: float
    ) -> HoldoutCheckOutput:
        node = self.graph.node(node_id)
        if scope_inside(event.scope, segment):
            return HoldoutCheckOutput(
                summary="the event's scope is exactly the anomalous segment: nothing to hold out",
                holdout={},
                rel_change=None,
                z=None,
                result="not_applicable",
            )
        where = f"({scope_where(event.scope)}) AND NOT ({segment_where(segment, node.dims)})"
        cells, rid = self.cells(node_id, window, None, where)
        cell = cells[0]
        rel, z = cell.rel_change, cell.z
        if abs(z) < HOLDOUT_Z and abs(rel) < 0.5 * abs(anomaly_rel):
            result, text = "refuted", "holdout normal"
        elif rel * anomaly_rel > 0 and abs(rel) >= 0.5 * abs(anomaly_rel) and abs(z) >= HOLDOUT_Z:
            result, text = "consistent", "holdout moves the same way"
        else:
            result, text = "inconclusive", "holdout partly moved"
        return HoldoutCheckOutput(
            summary=f"{text}: {rel:+.1%} (z {z:+.1f}) outside the segment vs {anomaly_rel:+.1%} inside",
            receipts=[rid],
            holdout={"scope": event.scope, "minus": segment, "where": where},
            rel_change=round(rel, 4),
            z=round(z, 2),
            result=result,
        )

    def segment_onset(
        self, node_id: str, segment: Segment, end: datetime, direction: str, max_hours: int = 24
    ) -> tuple[datetime | None, str]:
        """First hour of the run in which the segment itself deviates (|z| > 3, same direction), walking
        back from `end`. The root's onset can be earlier than the symptom's onset on the total."""
        node = self.graph.node(node_id)
        start = end - (max_hours - 1) * HOUR
        cond = f"ts BETWEEN {sql_ts(start - 4 * WEEK)} AND {sql_ts(end)}"
        rows, receipt = self.runner.query(
            hourly_sql(self.graph, node_id, cond, segment), self.as_of, purpose=f"hourly {node_id} in the root segment"
        )
        by_ts = {r["ts"]: r for r in rows}
        sign = -1 if direction == "down" else 1
        onset = None
        hour = end
        while hour >= start:
            cur = by_ts.get(hour)
            base = [b for k in range(1, 5) if (b := by_ts.get(hour - k * WEEK)) is not None]
            if cur is None or len(base) < 4:
                break
            if node.kind is NodeKind.RATIO:
                cell = Cell(
                    "h",
                    float(cur["num"] or 0),
                    sum(float(b["num"] or 0) for b in base) / 4,
                    float(cur["den"] or 0),
                    sum(float(b["den"] or 0) for b in base) / 4,
                )
            else:
                cell = Cell("h", float(cur["value"] or 0), sum(float(b["value"] or 0) for b in base) / 4)
            if not (abs(cell.z) > ONSET_Z and cell.z * sign > 0):
                break
            onset = hour
            hour -= HOUR
        return onset, receipt.id

    # ------------------------------------------------------------------ exact split
    def decompose_formula(self, node_id: str, segment: Segment, window: Window) -> DecomposeFormulaOutput | None:
        factors = product_factors(self.graph, node_id)
        if not factors:
            return None
        common = set(self.graph.node(node_id).dims)
        for f in factors:
            common &= set(self.graph.node(f).dims)
        seg = {d: v for d, v in segment.items() if d in common}
        needed: dict[str, set[str]] = defaultdict(set)
        for f in factors:
            for p in parts(self.graph, f):
                assert p.node.table and p.node.measure
                needed[p.node.table].add(p.node.measure)
        hours = window_hours(window)
        cur: dict[str, float] = {}
        base: dict[str, float] = {}
        receipts = []
        receipt_of: dict[str, str] = {}
        for tbl, measures in sorted(needed.items()):
            ms = sorted(measures)
            rows, receipt = self.runner.query(
                measures_window_sql(tbl, ms, window, segment_where(seg)),
                self.as_of,
                purpose=f"LMDI inputs from {tbl}" + (f" in {seg}" if seg else ""),
            )
            receipts.append(receipt.id)
            receipt_of[tbl] = receipt.id
            for m in ms:
                cur[m] = float(rows[0][f"cur_{m}"] or 0) / hours
                base[m] = float(rows[0][f"base_{m}"] or 0) / hours
        x0, x1 = {}, {}
        for f in factors:
            ps = parts(self.graph, f)
            if len(ps) == 1:
                m = ps[0].node.measure or ""
                x0[f], x1[f] = base[m], cur[m]
            else:
                n, d = ps[0].node.measure or "", ps[1].node.measure or ""
                x0[f] = base[n] / base[d] if base[d] else 0.0
                x1[f] = cur[n] / cur[d] if cur[d] else 0.0
        contrib, change, residual = lmdi(x0, x1)
        share = shares(contrib, change)
        contributions = [
            Contribution(
                node=f,
                share=round(share[f], 4),
                value=round(contrib[f], 4),
                receipt=receipt_of[parts(self.graph, f)[0].node.table or ""],
            )
            for f in sorted(factors, key=lambda k: -abs(contrib[k]))
        ]
        top = contributions[0]
        y0 = 1.0
        for v in x0.values():
            y0 *= v
        rel = change / y0 if y0 else 0.0
        return DecomposeFormulaOutput(
            summary=f"{node_id} {rel:+.1%} per hour: {top.node} carries {top.share:.0%} of the change",
            receipts=receipts,
            node=node_id,
            factors=factors,
            contributions=contributions,
            residual=residual,
        )
