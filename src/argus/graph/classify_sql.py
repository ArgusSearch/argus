"""SQL lineage for metric self-classification: what a C2 metric computes, in terms of graph nodes.

Everything here is deterministic and needs no data: the value expression rewritten over node ids, the node
kind and unit it implies, the segment a WHERE selects, joins that fan out, and the SQL rewrites the
classifier runs (the metric per hour as written, and the per-table repair of a fan-out join).
"""

from __future__ import annotations

import ast
import difflib
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import sqlglot
from sqlglot import exp

from argus.contracts.graph import Graph, NodeKind, Unit
from argus.contracts.metric import MetricSqlError
from argus.contracts.world import DIMENSIONS, table

Segment = dict[str, str]

_OPS: dict[type[exp.Expression], str] = {exp.Add: "+", exp.Sub: "-", exp.Mul: "*", exp.Div: "/"}
_UNIT_BASE: dict[str, dict[str, int]] = {
    "count": {"count": 1},
    "eur": {"eur": 1},
    "share": {},
    "ratio": {},
    "eur_per_unit": {"eur": 1, "count": -1},
}
_ACRONYMS = {"roas", "cvr", "cpc", "cpa", "ctr", "gmv", "aov", "cpm", "eur"}
SHARE_WORDS = frozenset({"rate", "share", "pct", "percent", "fraction"})


@dataclass(frozen=True)
class Lineage:
    """The value expression rewritten over node ids, as an `edge_tests.eval_expr` expression."""

    expr: str
    kind: NodeKind
    ingredients: list[str]
    """Additive node ids the expression sums, in order of appearance."""
    numerator: str | None = None
    denominator: str | None = None
    missing: tuple[str, str] | None = None
    """(table, measure) of a plain `SUM(measure)` whose measure has no node yet: the metric becomes that node."""


def _select(sql: str) -> exp.Select:
    tree = sqlglot.parse_one(sql, read="duckdb")
    if not isinstance(tree, exp.Select):
        raise MetricSqlError("SQL must be exactly one SELECT statement")
    return tree


def _from_tables(tree: exp.Select) -> list[exp.Table]:
    from_ = tree.args.get("from_") or tree.args.get("from")
    tables = [from_.this] if from_ is not None and isinstance(from_.this, exp.Table) else []
    tables += [j.this for j in tree.args.get("joins") or [] if isinstance(j.this, exp.Table)]
    return tables


def _value(tree: exp.Select) -> exp.Expression:
    value = next(p for p in tree.expressions if p.find(exp.AggFunc))
    return value.this if isinstance(value, exp.Alias) else value


def lineage(sql: str, graph: Graph, name: str) -> Lineage:
    """Map the metric's value expression onto node ids. Raises MetricSqlError with a contributor-facing reason."""
    tree = _select(sql)
    tables = _from_tables(tree)
    by_alias = {t.alias_or_name: t.name for t in tables}
    ingredients: list[str] = []
    missing: list[tuple[str, str]] = []

    def measure_node(agg: exp.Sum) -> str:
        col = agg.this
        if not isinstance(col, exp.Column):
            raise MetricSqlError(f"{agg.sql()}: SUM must wrap one measure column (write SUM(a) - SUM(b))")
        owners = (
            [by_alias[col.table]]
            if col.table in by_alias
            else [t.name for t in tables if col.name in table(t.name).measures]
        )
        if len(owners) != 1 or col.name not in table(owners[0]).measures:
            raise MetricSqlError(
                f"{agg.sql()}: {col.name!r} is not a measure of exactly one of {sorted(by_alias.values())}"
            )
        for node in graph.nodes:
            if node.kind is NodeKind.ADDITIVE and node.table == owners[0] and node.measure == col.name:
                ingredients.append(node.id)
                return node.id
        missing.append((owners[0], col.name))
        return name

    def walk(node: Any) -> str:
        if isinstance(node, exp.Paren):
            return f"({walk(node.this)})"
        if isinstance(node, exp.Cast | exp.TryCast | exp.Nullif):
            return walk(node.this)  # casts change the type, NULLIF(x, 0) only guards the division
        if isinstance(node, exp.Sum):
            return measure_node(node)
        if isinstance(node, exp.Count):
            raise MetricSqlError(
                f"{node.sql()}: COUNT counts rows of an hourly fact view, which depends on its storage grain; "
                "use SUM(<measure>)"
            )
        if isinstance(node, exp.Literal) and not node.is_string:
            return str(node.this)
        op = _OPS.get(type(node))
        if op is not None and isinstance(node, exp.Binary):
            return f"({walk(node.left)} {op} {walk(node.right)})"
        raise MetricSqlError(f"cannot place the value expression part {node.sql()}")

    expr = ast.unparse(ast.parse(walk(_value(tree)), mode="eval"))
    body = ast.parse(expr, mode="eval").body
    if missing and (len(missing) > 1 or not isinstance(body, ast.Name)):
        tbl, measure = missing[0]
        raise MetricSqlError(
            f"{tbl}.{measure} has no node yet; onboard it first as its own metric "
            f"(SELECT ts, SUM({measure}) AS value FROM {tbl} GROUP BY ALL)"
        )
    if isinstance(body, ast.Name):
        return Lineage(expr, NodeKind.ADDITIVE, ingredients, missing=missing[0] if missing else None)
    if (
        isinstance(body, ast.BinOp)
        and isinstance(body.op, ast.Div)
        and isinstance(body.left, ast.Name)
        and isinstance(body.right, ast.Name)
    ):
        return Lineage(expr, NodeKind.RATIO, ingredients, body.left.id, body.right.id)
    return Lineage(expr, NodeKind.DERIVED, ingredients)


def segment_of(sql: str) -> Segment:
    """The WHERE clause as a segment {dim: value}. Anything but `dim = 'value' AND ...` raises MetricSqlError."""
    where = _select(sql).args.get("where")
    if where is None:
        return {}
    segment: Segment = {}
    pending = [where.this]
    while pending:
        cond = pending.pop()
        if isinstance(cond, exp.Paren):
            pending.append(cond.this)
            continue
        if isinstance(cond, exp.And):
            pending += [cond.left, cond.right]
            continue
        if isinstance(cond, exp.EQ):
            col, lit = (cond.left, cond.right) if isinstance(cond.left, exp.Column) else (cond.right, cond.left)
            if isinstance(col, exp.Column) and isinstance(lit, exp.Literal) and lit.is_string:
                dim, value = col.name, str(lit.this)
                if dim not in DIMENSIONS or value not in DIMENSIONS[dim]:
                    raise MetricSqlError(f"WHERE {cond.sql()}: {value!r} is not a known value of a dimension")
                if segment.get(dim, value) != value:
                    raise MetricSqlError(f"WHERE asks for two values of {dim}; the metric is always empty")
                segment[dim] = value
                continue
        raise MetricSqlError(f"WHERE {cond.sql()}: only dim = 'value' conditions joined by AND can be placed")
    return segment


def fanout_problems(sql: str) -> list[str]:
    """Joins whose USING keys do not cover the grain of a joined view: each such row is counted several times."""
    tree = _select(sql)
    tables = [t.name for t in _from_tables(tree)]
    problems = []
    for i, join in enumerate(tree.args.get("joins") or []):
        keys = {u.name for u in join.args.get("using") or []}
        for name in tables[: i + 2]:
            below = [g for g in table(name).grain if g not in keys]
            if below:
                copies = math.prod(len(DIMENSIONS[d]) for d in below if d in DIMENSIONS)
                problems.append(
                    f"{name} has {', '.join(below)} below the join keys ({', '.join(sorted(keys))}): "
                    f"every row of the other side matches up to {copies} of its rows"
                )
    return problems


def hourly_as_written(sql: str, ts_condition: str) -> str:
    """The metric's own SQL at total level per hour: projection `ts, <value> AS value`, GROUP BY ts."""
    tree = _select(sql)
    value = next(p for p in tree.expressions if p.find(exp.AggFunc)).copy()
    tree.set("expressions", [exp.column("ts"), value])
    tree.set("group", exp.Group(expressions=[exp.column("ts")]))
    return tree.where(ts_condition, dialect="duckdb").order_by("ts").sql(dialect="duckdb")


def repair_sql(sql: str, graph: Graph, lin: Lineage, dims: list[str]) -> str:
    """The fan-out-free form of a ratio: aggregate each fact view to the shared keys, then divide."""
    assert lin.numerator and lin.denominator
    num, den = graph.node(lin.numerator), graph.node(lin.denominator)
    keys = ", ".join(["ts", *dims])
    where = _select(sql).args.get("where")
    cond = f" WHERE {where.this.sql(dialect='duckdb')}" if where is not None else ""
    return (
        f"WITH num AS (SELECT {keys}, SUM({num.measure}) AS num FROM {num.table}{cond} GROUP BY ALL),\n"
        f"     den AS (SELECT {keys}, SUM({den.measure}) AS den FROM {den.table}{cond} GROUP BY ALL)\n"
        f"SELECT {keys}, num::DOUBLE / NULLIF(den, 0) AS value\n"
        f"FROM num JOIN den USING ({keys})"
    )


def unified_diff(before: str, after: str, name: str) -> str:
    lines = difflib.unified_diff(
        before.strip().splitlines(),
        after.strip().splitlines(),
        f"{name}.yml (as written)",
        f"{name} (repaired)",
        lineterm="",
    )
    return "\n".join(lines)


def label_of(name: str) -> str:
    """`revenue_per_session` -> `Revenue per session`, `roas_by_advertiser` -> `ROAS by advertiser`."""
    text = " ".join(w.upper() if w in _ACRONYMS else w for w in name.split("_"))
    return text[0].upper() + text[1:]


def unit_of(expr: str, units: dict[str, Unit], values: np.ndarray | None = None) -> tuple[Unit, str]:
    """Dimensional analysis over node units; a dimensionless result is a share when every value is in [0, 1]."""

    def ev(node: ast.AST) -> dict[str, int] | None:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Name):
            return dict(_UNIT_BASE[units[node.id]])
        if isinstance(node, ast.Constant):
            return {}
        if isinstance(node, ast.BinOp):
            left, right = ev(node.left), ev(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add | ast.Sub):
                return left if left == right else None
            sign = 1 if isinstance(node.op, ast.Mult) else -1
            out = dict(left)
            for base, power in right.items():
                out[base] = out.get(base, 0) + sign * power
            return {b: p for b, p in out.items() if p}
        return None

    dims = ev(ast.parse(expr, mode="eval"))
    if dims is None:
        return "ratio", f"adds quantities of different units ({expr}); unit set to ratio"
    for unit in ("count", "eur", "eur_per_unit"):
        if dims == _UNIT_BASE[unit]:
            return unit, f"{unit} by dimensional analysis"
    if dims:
        return "ratio", f"unit {dims} has no C3 name; set to ratio"
    finite = values[np.isfinite(values)] if values is not None else np.array([])
    if len(finite) and finite.min() >= 0 and finite.max() <= 1:
        return "share", "dimensionless and always in [0, 1]"
    return "ratio", "dimensionless, can exceed 1"


def name_hint(name: str, graph: Graph) -> str | None:
    """The existing node a metric name points at, if any: `roas_by_advertiser` -> `roas`."""
    ids = {n.id for n in graph.nodes}
    base = name.partition("_by_")[0]
    return base if base in ids and base != name else None
