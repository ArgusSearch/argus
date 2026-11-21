"""Freshness gate: is the data for an hour complete enough to score?

Completeness of a table-hour is SUM(share) of its delivered micro-batches in `log_ingestion` (C1).
A node is scored for an hour only when every fact view it reads is complete for that hour; until then the
hour is *pending* and the node waits. Scoring partial data would turn a late batch into a fake drop, which
is exactly the false alarm Argus exists to avoid.

A table-hour that is still incomplete when it is due (scored hour = as_of minus the delivery lag) is *late*.
The gate reports a table once when it goes late and once when it has caught up, so the watcher can log
"fact_orders_hourly is 3 h behind" as a data-issue note instead of paging for a business drop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from argus.contracts.findings import TableFreshness
from argus.semantic.runner import Runner, sql_ts

HOUR = timedelta(hours=1)
COMPLETE = 1.0 - 1e-6


@dataclass(frozen=True)
class FreshnessState:
    """Completeness of every watched table for the recent hours, as seen at `as_of`."""

    as_of: datetime
    hour: datetime
    window_start: datetime
    completeness: dict[tuple[str, datetime], float]
    settled_through: dict[str, datetime]
    late_hours: dict[str, list[datetime]]
    went_late: list[str] = field(default_factory=list)
    caught_up: list[str] = field(default_factory=list)

    def of(self, table: str, hour: datetime) -> float:
        return self.completeness.get((table, hour), 1.0 if hour < self.window_start else 0.0)

    def complete(self, tables: list[str], hour: datetime) -> bool:
        return all(self.of(t, hour) >= COMPLETE for t in tables)

    def confidence(self, tables: list[str], hour: datetime) -> float:
        return min((self.of(t, hour) for t in tables), default=1.0)

    def table_freshness(self, tables: list[str]) -> list[TableFreshness]:
        return [
            TableFreshness(
                table=t,
                hour=self.hour,
                completeness=round(min(self.of(t, self.hour), 1.0), 6),
                status="ok" if self.of(t, self.hour) >= COMPLETE else "pending",
            )
            for t in tables
        ]


class FreshnessGate:
    """Reads `log_ingestion` once per tick for the last `lookback_hours` hours of every watched table.

    Hours older than the lookback are assumed complete (history is compacted and arrived long ago).
    """

    def __init__(self, runner: Runner, tables: list[str], lookback_hours: int = 48):
        self.runner = runner
        self.tables = sorted(tables)
        self.lookback = timedelta(hours=lookback_hours)
        self._late: set[str] = set()

    def check(self, as_of: datetime, hour: datetime) -> FreshnessState:
        start = hour - self.lookback + HOUR
        names = ", ".join(f"'{t}'" for t in self.tables)
        rows = self.runner.fetch(
            "SELECT table_name, ts, SUM(share) AS completeness FROM log_ingestion "
            f"WHERE table_name IN ({names}) AND ts BETWEEN {sql_ts(start)} AND {sql_ts(hour)} "
            "GROUP BY table_name, ts",
            as_of,
        )
        completeness: dict[tuple[str, datetime], float] = {
            (t, start + k * HOUR): 0.0 for t in self.tables for k in range(int(self.lookback / HOUR))
        }
        for row in rows:
            completeness[(str(row["table_name"]), row["ts"])] = float(row["completeness"] or 0.0)

        settled: dict[str, datetime] = {}
        late: dict[str, list[datetime]] = {}
        for t in self.tables:
            missing = sorted(h for (tt, h), c in completeness.items() if tt == t and c < COMPLETE)
            late[t] = missing
            settled[t] = missing[0] - HOUR if missing else hour

        now_late = {t for t, hours in late.items() if hours}
        went_late = sorted(now_late - self._late)
        caught_up = sorted(self._late - now_late)
        self._late = now_late
        return FreshnessState(
            as_of=as_of,
            hour=hour,
            window_start=start,
            completeness=completeness,
            settled_through=settled,
            late_hours=late,
            went_late=went_late,
            caught_up=caught_up,
        )

    def receipt_sql(self, table: str, start: datetime, end: datetime) -> str:
        """Self-contained SQL behind a data-issue note (completeness per hour of one table)."""
        return (
            "SELECT table_name, ts, SUM(share) AS completeness, COUNT(*) AS batches FROM log_ingestion "
            f"WHERE table_name = '{table}' AND ts BETWEEN {sql_ts(start)} AND {sql_ts(end)} "
            "GROUP BY table_name, ts ORDER BY ts"
        )
