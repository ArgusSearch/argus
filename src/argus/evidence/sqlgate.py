"""Validate and judge v2 self-written checks against the pinned world views."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from statistics import mean
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from argus.agent.types import SqlJudgement
from argus.contracts.world import ALL_TABLES
from argus.graph.classify_sql import fanout_problems
from argus.semantic.runner import Runner

_DIALECT = sqlglot.Dialect.get_or_raise("duckdb")
_MAX_ROWS = 200
_MAX_COLUMNS = 12
_COLUMNS: dict[str, object] = {
    spec.name: {column.name: column.sql_type for column in spec.columns} for spec in ALL_TABLES
}
_COLUMNS["log_events"] = {
    "log": "VARCHAR",
    "id": "VARCHAR",
    "ts": "TIMESTAMP",
    "kind": "VARCHAR",
    "scope": "JSON",
    "description": "VARCHAR",
}
_FUNCTIONS = {
    exp.Sum,
    exp.Count,
    exp.Avg,
    exp.Min,
    exp.Max,
    exp.Median,
    exp.PercentileCont,
    exp.StddevSamp,
    exp.Coalesce,
    exp.Nullif,
    exp.Abs,
    exp.Round,
    exp.Cast,
    exp.DateTrunc,
    exp.TimestampTrunc,
    exp.Extract,
    exp.Least,
    exp.Greatest,
    exp.Ln,
    exp.Exp,
    exp.Case,
    exp.If,
}
_SYNTAX = {
    exp.Select,
    exp.From,
    exp.Where,
    exp.Group,
    exp.Having,
    exp.Order,
    exp.Ordered,
    exp.Limit,
    exp.Distinct,
    exp.With,
    exp.CTE,
    exp.Table,
    exp.TableAlias,
    exp.Subquery,
    exp.Join,
    exp.Alias,
    exp.Star,
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Null,
    exp.Boolean,
    exp.Paren,
    exp.Var,
    exp.DataType,
    exp.DataTypeParam,
    exp.Interval,
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Mod,
    exp.Neg,
    exp.And,
    exp.Or,
    exp.Not,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Is,
    exp.In,
    exp.Between,
    exp.Exists,
    exp.Like,
    exp.ILike,
    exp.WithinGroup,
    exp.Filter,
    exp.Offset,
    exp.Tuple,
}
_SELECT_ARGS = {
    "expressions",
    "distinct",
    "from_",
    "where",
    "group",
    "having",
    "order",
    "limit",
    "offset",
    "with_",
    "joins",
}
_CAST_TYPES = {
    "BOOLEAN",
    "TINYINT",
    "SMALLINT",
    "INT",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINT",
    "UBIGINT",
    "UHUGEINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "VARCHAR",
    "TEXT",
    "DATE",
    "TIMESTAMP",
    "TIMESTAMPNTZ",
    "TIMESTAMPTZ",
    "TIME",
    "INTERVAL",
}


class _Rejected(ValueError):
    pass


def _parse(sql: str) -> exp.Select:
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 2000:
        raise _Rejected("length")
    tokens = _DIALECT.tokenize(sql)
    if any(token.comments for token in tokens):
        raise _Rejected("comments")
    statements = _DIALECT.parser().parse(tokens, sql)
    if len(statements) != 1 or not isinstance(tree := statements[0], exp.Select):
        raise _Rejected("single_select")
    if any(node.comments for node in tree.walk()):
        raise _Rejected("comments")
    return tree


def _check_syntax(tree: exp.Select) -> None:
    for node in tree.walk():
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise _Rejected("recursive_cte")
        if isinstance(node, exp.Table) and (
            not isinstance(node.this, exp.Identifier) or node.this.quoted or node.db or node.catalog
        ):
            raise _Rejected("table")
        if isinstance(node, exp.CTE) and node.alias_or_name.lower() in _COLUMNS:
            raise _Rejected("cte_shadow")
        if isinstance(node, exp.Select) and any(value for key, value in node.args.items() if key not in _SELECT_ARGS):
            raise _Rejected("select_syntax")
        if isinstance(node, exp.If) and not isinstance(node.parent, exp.Case):
            raise _Rejected("function")
        if isinstance(node, exp.Distinct) and node.args.get("on") is not None:
            raise _Rejected("select_syntax")
        if isinstance(node, exp.DataType) and node.this.value not in _CAST_TYPES:
            raise _Rejected("cast_type")
        if type(node) not in _FUNCTIONS and type(node) not in _SYNTAX:
            raise _Rejected("function" if isinstance(node, exp.Func) else "select_syntax")


def _check_sources(tree: exp.Select) -> None:
    if sum(1 for _ in tree.find_all(exp.Join)) > 2:
        raise _Rejected("join_limit")
    # Resolve each reference in its own scope. A name used by a CTE elsewhere does not authorize a scan.
    for scope in traverse_scope(tree):
        for _, source in scope.selected_sources.values():
            if isinstance(source, exp.Table) and source.name.lower() not in _COLUMNS:
                raise _Rejected("table")

        joins = scope.expression.args.get("joins") or []
        if not joins:
            continue
        if any(join.kind == "CROSS" or not join.args.get("using") for join in joins):
            raise _Rejected("join_keys")
        # The shared grain checker works on direct contract tables. Log and derived sources have no
        # contract grain it can prove unique, so use a grouped comparison or scalar subquery instead.
        if any(
            not isinstance(source, exp.Table) or source.name.lower().startswith("log_")
            for _, source in scope.selected_sources.values()
        ):
            raise _Rejected("join_grain")
        statement = scope.expression.copy()
        for source in statement.find_all(exp.Table):
            source.this.set("this", source.name.lower())
        for join in statement.find_all(exp.Join):
            for key in join.args.get("using") or []:
                key.set("this", key.name.lower())
        if fanout_problems(statement.sql(dialect="duckdb")):
            raise _Rejected("fanout")
        # The static dimension's key is an attribute in C1, so fanout_problems has no grain for it.
        if any(
            isinstance(source, exp.Table) and source.name.lower() == "dim_advertiser"
            for _, source in scope.selected_sources.values()
        ) and any("advertiser_id" not in {column.name.lower() for column in join.args["using"]} for join in joins):
            raise _Rejected("fanout")


def _checked_sql(sql: str) -> str:
    tree = _parse(sql)
    _check_syntax(tree)
    _check_sources(tree)
    # Expand wildcards on a copy so empty results and CTEs obey the same column cap. Keep DuckDB's
    # original output names in the executed query, including aliases used by the prediction.
    shaped = qualify(tree.copy(), dialect="duckdb", schema=_COLUMNS, validate_qualify_columns=False)
    if len(shaped.expressions) > _MAX_COLUMNS or any(column.is_star for column in shaped.expressions):
        raise _Rejected("column_limit")
    for select, projection in zip(tree.find_all(exp.Select), shaped.find_all(exp.Select), strict=True):
        if select.args.get("limit") is None and select.args.get("offset") is None:
            continue
        order = select.args.get("order")
        if order is None:
            select.order_by("ALL", dialect="duckdb", copy=False)
        elif not any(isinstance(item.this, exp.Var) and item.this.name.upper() == "ALL" for item in order.expressions):
            # Break ties in a user-ordered LIMIT using all projected columns.
            select.order_by(*(str(i) for i in range(1, len(projection.expressions) + 1)), dialect="duckdb", copy=False)
    return tree.sql(dialect="duckdb", unsupported_level=ErrorLevel.RAISE)


def _reject(rule: str) -> SqlJudgement:
    return SqlJudgement(accepted=False, rule=rule, summary=f"SQL check rejected ({rule}).")


def _check(sql: str) -> tuple[str | None, SqlJudgement]:
    try:
        canonical = _checked_sql(sql)
    except _Rejected as exc:
        return None, _reject(str(exc))
    except Exception:
        return None, _reject("syntax")
    return canonical, SqlJudgement(accepted=True, summary="SQL check accepted.")


def validate(sql: str) -> SqlJudgement:
    """Return the first violated rule without opening a connection."""
    return _check(sql)[1]


def _prediction(predict: dict[str, Any]) -> tuple[str, str, list[Any], list[Any] | str, str, float]:
    value, group, a, b, relation, min_gap = (predict[k] for k in ("value", "group", "a", "b", "relation", "min_gap"))
    if (
        not isinstance(value, str)
        or not value
        or not isinstance(group, str)
        or not group
        or value == group
        or not isinstance(a, list)
        or not a
        or (b != "rest" and (not isinstance(b, list) or not b or any(item in a for item in b)))
        or any(type(item) not in (str, bool, int, float) for item in a + (b if isinstance(b, list) else []))
        or relation not in ("a_lt_b", "a_gt_b", "a_eq_b")
        or type(min_gap) not in (int, float)
        or not math.isfinite(min_gap)
        or min_gap < 0
    ):
        raise ValueError("invalid prediction")
    return value, group, a, b, relation, min_gap


def run_check(runner: Runner, sql: str, as_of: datetime, predict: dict[str, Any], purpose: str) -> SqlJudgement:
    """Run a validated cut on the case's own clock and judge two sets of values."""
    canonical, result = _check(sql)
    if canonical is None:
        return result
    try:
        value, group, a, b, relation, min_gap = _prediction(predict)
    except (KeyError, ValueError, TypeError, OverflowError):
        return _reject("prediction")
    try:
        rows, receipt = runner.query(
            f"SELECT * FROM ({canonical}) ORDER BY ALL LIMIT {_MAX_ROWS}", as_of, purpose=f"agent sql_check: {purpose}"
        )
    except Exception:
        return _reject("execution")
    result.receipt_id = receipt.id
    result.rows = rows
    if len(rows) >= _MAX_ROWS:
        result.summary = "Prediction inconclusive: result reached the row limit."
        return result
    left: list[float] = []
    right: list[float] = []
    for row in rows:
        key, number = row.get(group), row.get(value)
        if key is None or isinstance(number, bool) or not isinstance(number, (int, float, Decimal)):
            continue
        number = float(number)
        if not math.isfinite(number):
            continue
        if key in a:
            left.append(number)
        elif b == "rest" or key in b:
            right.append(number)
    if not left or not right:
        result.summary = "Prediction inconclusive: both groups need a finite numeric value."
        return result
    avg_a, avg_b = mean(left), mean(right)
    delta = avg_a - avg_b
    gap = delta / abs(avg_b) if avg_b else math.copysign(math.inf, delta) if delta else 0.0
    holds = {
        "a_lt_b": gap < 0 and -gap >= min_gap,
        "a_gt_b": gap > 0 and gap >= min_gap,
        "a_eq_b": abs(gap) <= min_gap,
    }[relation]
    result.outcome = "holds" if holds else "fails"
    result.summary = "Prediction holds." if holds else "Prediction fails."
    return result
