"""Immutable, normalized provider data consumed by the normal receipt runner."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from tempfile import NamedTemporaryFile

import duckdb

from argus.connectors import plausible, stripe
from argus.connectors.provider import Metric, ProviderId, Report

METRICS: dict[ProviderId, tuple[Metric, ...]] = {"plausible": plausible.METRICS, "stripe": stripe.METRICS}
TABLES = {
    metric.table: (provider, metric)
    for provider, metrics in METRICS.items()
    for metric in metrics
    if not metric.numerator
}
TABLE_REFERENCE = re.compile(r"\b(" + "|".join(TABLES) + r")\b", re.IGNORECASE)
FILENAME = re.compile(r"(\d{8}T\d{12})_(\d{8})(?:_([a-z]{3}))?\.parquet")
STAMP = "%Y%m%dT%H%M%S%f"
SOURCE_PREFIX = "connector:"


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class Snapshot:
    provider: ProviderId
    synced_at: datetime  # naive UTC, like a Runner receipt
    latest_day: date
    path: Path
    currency: str | None

    @property
    def latest_hour(self) -> datetime:
        return datetime.combine(self.latest_day, time())


class SourceData:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def snapshots(self, provider: ProviderId) -> list[Snapshot]:
        results = []
        for path in sorted((self.directory / provider).glob("*.parquet"), reverse=True):
            match = FILENAME.fullmatch(path.name)
            if match is not None:
                stamp, day, currency = match.groups()
                try:
                    synced = datetime.strptime(stamp, STAMP)
                    latest = datetime.strptime(day, "%Y%m%d").date()
                except ValueError:
                    continue
                results.append(Snapshot(provider, synced, latest, path, currency))
        return results

    def latest(self, provider: ProviderId, as_of: datetime = datetime.max) -> Snapshot | None:
        return next((item for item in self.snapshots(provider) if item.synced_at <= as_of), None)

    def store(self, provider: ProviderId, report: Report, currency: str | None = None) -> Snapshot:
        synced = datetime.now(UTC).replace(tzinfo=None)
        folder = self.directory / provider
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        suffix = f"_{currency}" if currency else ""
        path = folder / f"{synced:{STAMP}}_{report.latest_day:%Y%m%d}{suffix}.parquet"
        with NamedTemporaryFile(dir=folder, prefix=".pending-", delete=False) as file:
            temp = Path(file.name)
        try:
            with duckdb.connect(":memory:") as db:
                db.execute("CREATE TABLE observations (metric VARCHAR, ts TIMESTAMP, dimension VARCHAR, value BIGINT)")
                if report.rows:
                    db.executemany(
                        "INSERT INTO observations VALUES (?, ?, ?, ?)", [row.values() for row in report.rows]
                    )
                db.execute(f"COPY observations TO {quote(str(temp))} (FORMAT PARQUET)")
            temp.chmod(0o600)
            os.link(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return Snapshot(provider, synced, report.latest_day, path, currency)

    def prepare(self, cursor: duckdb.DuckDBPyConnection, sql: str, as_of: datetime) -> None:
        """Set up only provider views used by this query, pinned to the same time as its receipt."""
        tables = {name.lower() for name in TABLE_REFERENCE.findall(sql)}
        sources = {provider: self.latest(provider, as_of) for provider in {TABLES[t][0] for t in tables}}
        for table in sorted(tables):
            provider, metric = TABLES[table]
            snapshot = sources[provider]
            dimension = f", dimension AS {metric.dimension}" if metric.dimension else ""
            if snapshot:
                select = (
                    f"SELECT ts, value AS amount{dimension} FROM read_parquet({quote(str(snapshot.path))}) "
                    f"WHERE metric = {quote(metric.id)}"
                )
            else:
                dim = f", NULL::VARCHAR AS {metric.dimension}" if metric.dimension else ""
                select = f"SELECT NULL::TIMESTAMP AS ts, NULL::BIGINT AS amount{dim} WHERE FALSE"
            cursor.execute(f"CREATE OR REPLACE TEMP VIEW {table} AS {select}")
