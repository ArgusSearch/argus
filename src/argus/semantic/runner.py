"""Query runner with receipts.

Every query runs with `as_of` pinned (`SET VARIABLE as_of`), so the fact_/log_ views show exactly the data
that had arrived at that moment. The result hash is canonical: rows sorted, floats rounded to 10
significant digits, then SHA-256. Re-running a receipt therefore returns the same hash even after late
data has arrived, which is what "click the number, re-run the SQL, same hash" relies on.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from argus.contracts.findings import Receipt
from argus.contracts.world import AS_OF_VARIABLE


def canonical_hash(rows: list[tuple[Any, ...]]) -> str:
    def norm(value: Any) -> Any:
        if isinstance(value, float):
            return float(f"{value:.10g}")
        if isinstance(value, int | bool) or value is None:
            return value
        return str(value)

    canon = sorted(json.dumps([norm(v) for v in row]) for row in rows)
    return "sha256:" + hashlib.sha256("\n".join(canon).encode()).hexdigest()[:16]


def sql_ts(ts: datetime) -> str:
    return f"TIMESTAMP '{ts:%Y-%m-%d %H:%M:%S}'"


class Runner:
    """Read-only access to a world. One instance per Argus process; safe to use from several threads."""

    def __init__(self, world_path: str | Path):
        self.world_path = Path(world_path)
        self._con = duckdb.connect(str(self.world_path), read_only=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self.receipts: dict[str, Receipt] = {}
        self.query_count = 0

    def _cursor(self) -> duckdb.DuckDBPyConnection:
        cur = getattr(self._local, "cur", None)
        if cur is None:
            cur = self._con.cursor()
            self._local.cur = cur
        return cur

    def _execute(self, sql: str, as_of: datetime) -> tuple[list[tuple[Any, ...]], list[str]]:
        cur = self._cursor()
        cur.execute(f"SET VARIABLE {AS_OF_VARIABLE} = {sql_ts(as_of)}")
        result = cur.execute(sql)
        columns = [d[0] for d in result.description] if result.description else []
        return result.fetchall(), columns

    def fetch(self, sql: str, as_of: datetime) -> list[dict[str, Any]]:
        """Run a query without a receipt (monitoring internals). Returns rows as dicts."""
        rows, cols = self._execute(sql, as_of)
        with self._lock:
            self.query_count += 1
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def query(self, sql: str, as_of: datetime, purpose: str = "") -> tuple[list[dict[str, Any]], Receipt]:
        """Run a query and record a receipt. Use this for every number a human will see."""
        started = time.perf_counter()
        rows, cols = self._execute(sql, as_of)
        ms = (time.perf_counter() - started) * 1000
        with self._lock:
            self.query_count += 1
            rid = f"r{len(self.receipts) + 1}"
            receipt = Receipt(
                id=rid,
                sql=sql.strip(),
                as_of=as_of,
                result_hash=canonical_hash(rows),
                rows=len(rows),
                ms=round(ms, 2),
                purpose=purpose,
            )
            self.receipts[rid] = receipt
        return [dict(zip(cols, r, strict=True)) for r in rows], receipt

    def rerun(self, receipt_id: str) -> tuple[str, bool]:
        """Re-run a receipt's SQL at its pinned as_of. Returns (hash, matches)."""
        receipt = self.receipts[receipt_id]
        rows, _ = self._execute(receipt.sql, receipt.as_of)
        new_hash = canonical_hash(rows)
        return new_hash, new_hash == receipt.result_hash

    def close(self) -> None:
        self._con.close()
