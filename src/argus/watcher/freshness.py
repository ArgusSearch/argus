"""Freshness gate: data before business.

A table-hour is complete when all its micro-batches have arrived (SUM(share) = 1 in log_ingestion).
A node is scored for an hour only when every source table is complete for that hour; otherwise the hour
is `pending`. A drop that only appears on pending data must become a DATA_ISSUE note, never a page.
"""

from __future__ import annotations

from datetime import datetime

from argus.contracts.findings import TableFreshness
from argus.semantic.compile import quote
from argus.semantic.runner import Runner, sql_ts

COMPLETE = 0.999
DATA_ISSUE_BELOW = 0.8


def freshness_sql(tables: list[str], start: datetime, end: datetime) -> str:
    names = ", ".join(quote(t) for t in sorted(tables))
    return (
        "SELECT table_name, ts, SUM(share) AS completeness FROM log_ingestion "
        f"WHERE table_name IN ({names}) AND ts BETWEEN {sql_ts(start)} AND {sql_ts(end)} "
        "GROUP BY table_name, ts ORDER BY table_name, ts"
    )


def completeness(
    runner: Runner, tables: list[str], start: datetime, end: datetime, as_of: datetime
) -> dict[tuple[str, datetime], float]:
    """(table, hour) -> completeness for every hour in [start, end]; missing hours count as 0."""
    rows = runner.fetch(freshness_sql(tables, start, end), as_of)
    return {(r["table_name"], r["ts"]): float(r["completeness"]) for r in rows}


def hour_freshness(runner: Runner, tables: list[str], hour: datetime, as_of: datetime) -> list[TableFreshness]:
    found = completeness(runner, tables, hour, hour, as_of)
    out = []
    for name in sorted(tables):
        value = min(1.0, found.get((name, hour), 0.0))
        out.append(
            TableFreshness(
                table=name, hour=hour, completeness=round(value, 4), status="ok" if value >= COMPLETE else "pending"
            )
        )
    return out
