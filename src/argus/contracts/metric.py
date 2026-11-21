"""C2 metric definition: the only thing a contributor ever writes to add a metric.

A metric is a dbt-style YAML file in `metrics/` with exactly three keys:

```yaml
name: roas_by_advertiser
description: Return on ad spend per advertiser
sql: |
  SELECT ts, advertiser_id, country,
         SUM(attributed_gmv) / NULLIF(SUM(ad_spend), 0) AS value
  FROM fact_ads_hourly
  GROUP BY ALL
```

The contributor never says where the metric goes in the graph; the cartographer (lane G) works that out.

Allowed SQL form in the hackathon version (anything else is rejected with a clear reason):

* one `SELECT` statement, no CTEs, subqueries or window functions;
* the projection contains `ts`, zero or more dimension columns, and exactly one value expression aliased `value`;
* the value expression is built from aggregates (`SUM`, `COUNT`) combined with `+ - * /`, `NULLIF`, `CAST`;
* `FROM` names only `fact_*` views, joined with `JOIN ... USING (...)`;
* `WHERE` filters and `GROUP BY` (explicit or `ALL`) are allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp

from argus.contracts.world import DIMENSIONS, FACT_TABLES


class MetricDefinition(BaseModel):
    """The C2 contract. Extra keys are rejected on purpose."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="snake_case metric id, unique in the graph")
    description: str = Field(min_length=1, description="one sentence, used by the cartographer and the LLM")
    sql: str = Field(min_length=1, description="SELECT in the allowed form (see module docstring)")


class MetricSqlError(ValueError):
    """Raised when a metric's SQL is outside the allowed form. The message is shown to the contributor."""


@dataclass(frozen=True)
class ParsedMetric:
    """Facts extracted from a metric's SQL, the input of the cartographer's placement pipeline."""

    name: str
    tables: list[str]
    dims: list[str]
    value_sql: str
    aggregates: list[str]
    join_keys: list[str] = field(default_factory=list)
    numerator_sql: str | None = None
    denominator_sql: str | None = None
    has_where: bool = False


_ALLOWED_AGGS = (exp.Sum, exp.Count)
_FACT_NAMES = {t.name for t in FACT_TABLES}


def load_metric(path: str | Path) -> MetricDefinition:
    data = yaml.safe_load(Path(path).read_text())
    return MetricDefinition.model_validate(data)


def parse_metric(metric: MetricDefinition) -> ParsedMetric:
    """Validate the SQL form and extract tables, dimensions and the value expression."""
    try:
        statements = sqlglot.parse(metric.sql, read="duckdb")
    except sqlglot.errors.ParseError as err:
        raise MetricSqlError(f"SQL does not parse: {err}") from err
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise MetricSqlError("SQL must be exactly one SELECT statement")
    tree = statements[0]
    if tree.find(exp.With) or tree.find(exp.Subquery) or tree.find(exp.Window):
        raise MetricSqlError("CTEs, subqueries and window functions are not allowed")

    tables = sorted({t.name for t in tree.find_all(exp.Table)})
    unknown = [t for t in tables if t not in _FACT_NAMES]
    if unknown:
        raise MetricSqlError(f"unknown or non-fact tables {unknown}; allowed: {sorted(_FACT_NAMES)}")

    join_keys: list[str] = []
    for join in tree.args.get("joins") or []:
        using = join.args.get("using")
        if not using:
            raise MetricSqlError("joins must use JOIN ... USING (keys)")
        join_keys += [u.name for u in using]

    dims: list[str] = []
    value: exp.Expression | None = None
    for proj in tree.expressions:
        if proj.find(exp.AggFunc):
            if value is not None:
                raise MetricSqlError("exactly one aggregated value expression is allowed")
            if proj.alias_or_name != "value":
                raise MetricSqlError("the aggregated expression must be aliased AS value")
            value = proj.this if isinstance(proj, exp.Alias) else proj
        else:
            name = proj.alias_or_name
            if name != "ts" and name not in DIMENSIONS:
                raise MetricSqlError(f"column {name!r} is neither ts nor a known dimension {sorted(DIMENSIONS)}")
            dims.append(name)
    if "ts" not in dims:
        raise MetricSqlError("the projection must include ts")
    if value is None:
        raise MetricSqlError("missing the aggregated value expression (... AS value)")
    for agg in value.find_all(exp.AggFunc):
        if not isinstance(agg, _ALLOWED_AGGS):
            raise MetricSqlError(f"aggregate {agg.sql()} is not allowed; use SUM or COUNT")
    if not tree.args.get("group"):
        raise MetricSqlError("GROUP BY is required (explicit keys or GROUP BY ALL)")

    numerator = denominator = None
    core = value.unnest()
    if isinstance(core, exp.Div):
        numerator = core.left.sql(dialect="duckdb")
        denominator = core.right.sql(dialect="duckdb")

    return ParsedMetric(
        name=metric.name,
        tables=tables,
        dims=[d for d in dims if d != "ts"],
        value_sql=value.sql(dialect="duckdb"),
        aggregates=[a.sql(dialect="duckdb") for a in value.find_all(exp.AggFunc)],
        join_keys=join_keys,
        numerator_sql=numerator,
        denominator_sql=denominator,
        has_where=tree.args.get("where") is not None,
    )
