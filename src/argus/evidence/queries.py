"""Capture the exact read dependencies of a tool and re-derive them against pinned data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from argus.contracts.findings import Receipt
from argus.semantic.runner import Runner, canonical_hash


class ProofMismatch(ValueError):
    """A read no longer matches the binding minted at dispatch."""


@dataclass(frozen=True)
class Query:
    receipt: Receipt
    columns: tuple[str, ...]
    recorded: bool

    def read(self, runner: Runner) -> list[dict[str, Any]]:
        original = runner.receipts.get(self.receipt.id)
        if original != self.receipt:
            raise ProofMismatch("The receipt differs from the one produced by the tool.")
        rows = runner.fetch(self.receipt.sql, self.receipt.as_of)
        if (
            len(rows) != self.receipt.rows
            or any(tuple(row) != self.columns for row in rows)
            or canonical_hash([tuple(row.values()) for row in rows]) != self.receipt.result_hash
        ):
            raise ProofMismatch("The rows no longer match the receipt at its pinned clock.")
        return rows


class CaptureRunner(Runner):
    """Runner interface used by tools, with one read transcript per call."""

    def __init__(self, runner: Runner):
        self.runner = runner
        self.queries: list[Query] = []
        self.rows: dict[str, list[dict[str, Any]]] = {}

    def _record(
        self, sql: str, as_of: datetime, purpose: str, *, recorded: bool
    ) -> tuple[list[dict[str, Any]], Receipt]:
        rows, receipt = self.runner.query(sql, as_of, purpose)
        self.queries.append(Query(receipt.model_copy(deep=True), tuple(rows[0]) if rows else (), recorded))
        self.rows[receipt.id] = rows
        return rows, receipt

    def query(self, sql: str, as_of: datetime, purpose: str = "") -> tuple[list[dict[str, Any]], Receipt]:
        return self._record(sql, as_of, purpose, recorded=True)

    def fetch(self, sql: str, as_of: datetime) -> list[dict[str, Any]]:
        rows, _ = self._record(sql, as_of, "", recorded=False)
        return rows


class ProofRunner(Runner):
    """Only replay the queries that the trusted tool generated for this particular call."""

    def __init__(self, runner: Runner, queries: tuple[Query, ...]):
        self.runner = runner
        self.queries = queries
        self.index = 0
        self.rows: dict[str, list[dict[str, Any]]] = {}

    def _next(self, sql: str, as_of: datetime, purpose: str, *, recorded: bool) -> tuple[list[dict[str, Any]], Receipt]:
        if self.index >= len(self.queries):
            raise ProofMismatch("The tool issued an extra read during verification.")
        query = self.queries[self.index]
        receipt = query.receipt
        if (sql.strip(), as_of, purpose, recorded) != (receipt.sql, receipt.as_of, receipt.purpose, query.recorded):
            raise ProofMismatch("The tool query differs from its original binding.")
        self.index += 1
        rows = query.read(self.runner)
        self.rows[receipt.id] = rows
        return rows, receipt

    def query(self, sql: str, as_of: datetime, purpose: str = "") -> tuple[list[dict[str, Any]], Receipt]:
        return self._next(sql, as_of, purpose, recorded=True)

    def fetch(self, sql: str, as_of: datetime) -> list[dict[str, Any]]:
        rows, _ = self._next(sql, as_of, "", recorded=False)
        return rows

    def finish(self) -> None:
        if self.index != len(self.queries):
            raise ProofMismatch("The tool skipped a read during verification.")
