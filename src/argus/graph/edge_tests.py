"""Edge tests: every edge is a contract that is re-checked against the data.

* formula / identity_residual: target and expr(sources) per hour over the last `window_days`;
  median and p95 relative residual must stay under the thresholds.
* breakdown / children_sum: the known values of the dimension sum to the parent every hour
  (for a ratio, numerator and denominator are checked separately).
* cause / lagged_corr_bh and evidence / onset_alignment: not run here yet (cause is lane G Stage 2,
  evidence is checked inside every investigation).

A failing formula or breakdown test sets the edge BROKEN and appends a GraphChange. A broken identity
also tells the investigator that a drop is a data problem, not a business problem.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from argus.contracts.graph import Edge, EdgeKind, EdgeStatus, EdgeTestResult, Graph
from argus.contracts.world import DIMENSIONS
from argus.graph.store import Changelog
from argus.semantic.compile import hourly_sql, parts, quote
from argus.semantic.runner import Runner, sql_ts

_OPS: dict[type[ast.operator], Callable[[np.ndarray, np.ndarray], np.ndarray]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def eval_expr(expr: str, values: dict[str, np.ndarray]) -> np.ndarray:
    """Evaluate arithmetic over node ids (+ - * / and parentheses only)."""

    def ev(node: ast.AST) -> np.ndarray:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return np.asarray(float(node.value))
        raise ValueError(f"unsupported expression element {ast.dump(node)}")

    return ev(ast.parse(expr, mode="eval"))


@dataclass
class EdgeStatusChange:
    edge: Edge
    old: EdgeStatus | None
    new: EdgeStatus
    result: EdgeTestResult


class EdgeTester:
    """Runs the seed edge tests at a given as_of over complete hours only."""

    def __init__(self, graph: Graph, runner: Runner, lag_hours: int = 2):
        self.graph = graph
        self.runner = runner
        self.lag = timedelta(hours=lag_hours)

    def _series(
        self, node_id: str, start: datetime, end: datetime, as_of: datetime, cache: dict[str, tuple[np.ndarray, str]]
    ) -> tuple[np.ndarray, str]:
        if node_id not in cache:
            cond = f"ts BETWEEN {sql_ts(start)} AND {sql_ts(end)}"
            rows, receipt = self.runner.query(
                hourly_sql(self.graph, node_id, cond), as_of, purpose=f"edge test: hourly {node_id}"
            )
            if "value" in (rows[0] if rows else {}):
                vals = np.array([float(r["value"] or 0) for r in rows])
            else:
                vals = np.array([float(r["num"] or 0) / float(r["den"]) if r["den"] else np.nan for r in rows])
            cache[node_id] = (vals, receipt.id)
        return cache[node_id]

    def test_formula(self, edge: Edge, as_of: datetime, cache: dict[str, tuple[np.ndarray, str]]) -> EdgeTestResult:
        assert edge.test and edge.expr
        end = (as_of - self.lag).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=edge.test.window_days) + timedelta(hours=1)
        target, rid = self._series(edge.target, start, end, as_of, cache)
        values, receipts = {}, [rid]
        for src in edge.sources:
            values[src], r = self._series(src, start, end, as_of, cache)
            receipts.append(r)
        predicted = eval_expr(edge.expr, values)
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.abs(target - predicted) / np.abs(target)
        rel = rel[np.isfinite(rel)]
        median = float(np.median(rel)) if len(rel) else float("nan")
        p95 = float(np.percentile(rel, 95)) if len(rel) else float("nan")
        passed = bool(len(rel) and median <= (edge.test.median_max or 0) and p95 <= (edge.test.p95_max or 0))
        return EdgeTestResult(
            ran_at=as_of, passed=passed, median_rel=median, p95_rel=p95, hours=len(rel), receipts=receipts
        )

    def test_breakdown(self, edge: Edge, as_of: datetime) -> EdgeTestResult:
        assert edge.test and edge.dim
        end = (as_of - self.lag).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=edge.test.window_days) + timedelta(hours=1)
        known = ", ".join(quote(v) for v in DIMENSIONS[edge.dim])
        worst, hours, receipts = 0.0, 0, []
        for part in parts(self.graph, edge.target):
            m = part.node.measure
            sql = (
                f"SELECT ts, SUM({m}) AS total, SUM({m}) FILTER (WHERE {edge.dim} IN ({known})) AS children "
                f"FROM {part.node.table} WHERE ts BETWEEN {sql_ts(start)} AND {sql_ts(end)} GROUP BY ts"
            )
            rows, receipt = self.runner.query(sql, as_of, purpose=f"edge test {edge.id}: children sum")
            receipts.append(receipt.id)
            for r in rows:
                total = float(r["total"] or 0)
                if total:
                    worst = max(worst, abs(total - float(r["children"] or 0)) / abs(total))
            hours = max(hours, len(rows))
        passed = bool(hours and worst <= (edge.test.max_rel_err or 0))
        return EdgeTestResult(ran_at=as_of, passed=passed, max_rel_err=worst, hours=hours, receipts=receipts)

    def run_all(self, as_of: datetime, changelog: Changelog) -> list[EdgeStatusChange]:
        """Test every formula and breakdown edge; return the edges whose status changed (or first ran)."""
        cache: dict[str, tuple[np.ndarray, str]] = {}
        changes: list[EdgeStatusChange] = []
        updated = []
        for edge in self.graph.edges:
            if edge.kind is EdgeKind.FORMULA:
                result = self.test_formula(edge, as_of, cache)
            elif edge.kind is EdgeKind.BREAKDOWN:
                result = self.test_breakdown(edge, as_of)
            else:
                note = (
                    "lagged correlation test not implemented yet (lane G, Stage 2)"
                    if edge.kind is EdgeKind.CAUSE
                    else "checked per investigation: onset alignment and scope match"
                )
                updated.append(
                    edge.model_copy(update={"last_test": EdgeTestResult(ran_at=as_of, passed=None, note=note)})
                )
                continue
            new_status = EdgeStatus.VALID if result.passed else EdgeStatus.BROKEN
            first_run = edge.last_test is None
            changed = new_status is not edge.status
            if changed:
                changelog.append(
                    sim_ts=as_of,
                    kind="edge_status",
                    edge=edge.id,
                    old_status=edge.status,
                    new_status=new_status,
                    reason=_reason(edge, result),
                    receipts=result.receipts,
                )
            if changed or first_run:
                changes.append(EdgeStatusChange(edge, edge.status if changed else None, new_status, result))
            updated.append(edge.model_copy(update={"status": new_status, "last_test": result}))
        self.graph = self.graph.model_copy(update={"edges": updated})
        return changes


def _reason(edge: Edge, result: EdgeTestResult) -> str:
    if edge.kind is EdgeKind.FORMULA:
        return f"identity residual median {result.median_rel:.2e}, p95 {result.p95_rel:.2e} over {result.hours} h"
    return f"children sum max relative error {result.max_rel_err:.2e} over {result.hours} h"
