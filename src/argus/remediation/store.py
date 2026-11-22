"""Durable action state: one SQLite file per factual world, every transition a conditional update.

A transition commits only from the states it names (`BEGIN IMMEDIATE` serialises writers across threads
and processes), so a double click, a retry and a restarted server all see one decision and one execution.
Every transition also appends a journal row. Effect receipts are stored next to the proposals so links stay
resolvable after a restart.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from argus.agent.types import Decision, EffectResult, ProposalView, ReceiptLink
from argus.contracts.findings import Receipt
from argus.remediation.models import Execution

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    identity TEXT NOT NULL UNIQUE,
    digest TEXT NOT NULL UNIQUE,
    frozen TEXT NOT NULL,
    state TEXT NOT NULL,
    decision TEXT,
    decision_key TEXT,
    execution TEXT,
    effect TEXT
);
CREATE TABLE IF NOT EXISTS journal (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    sim_ts TEXT,
    from_state TEXT,
    to_state TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    proposal_id TEXT NOT NULL,
    world_revision TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (proposal_id, world_revision, receipt_id)
);
"""


class ActionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as con:
            for statement in filter(str.strip, SCHEMA.split(";")):
                con.execute(statement)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
        finally:
            con.close()

    # ------------------------------------------------------------------ reads

    def _view(self, row: sqlite3.Row | tuple[Any, ...]) -> ProposalView:
        frozen, state, decision, effect = row
        view = ProposalView.model_validate_json(frozen)
        return view.model_copy(
            update={
                "state": state,
                "decision": Decision.model_validate_json(decision) if decision else None,
                "effect": EffectResult.model_validate_json(effect) if effect else None,
            }
        )

    def get(self, proposal_id: str) -> ProposalView | None:
        with self._tx() as con:
            row = con.execute("SELECT frozen, state, decision, effect FROM proposals WHERE id = ?", (proposal_id,))
            found = row.fetchone()
        return self._view(found) if found else None

    def by_identity(self, identity: str) -> ProposalView | None:
        with self._tx() as con:
            found = con.execute(
                "SELECT frozen, state, decision, effect FROM proposals WHERE identity = ?", (identity,)
            ).fetchone()
        return self._view(found) if found else None

    def all(self) -> list[ProposalView]:
        with self._tx() as con:
            rows = con.execute("SELECT frozen, state, decision, effect FROM proposals ORDER BY seq").fetchall()
        return [self._view(r) for r in rows]

    def decision_key(self, proposal_id: str) -> str | None:
        with self._tx() as con:
            row = con.execute("SELECT decision_key FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return row[0] if row else None

    def execution(self, proposal_id: str) -> Execution | None:
        with self._tx() as con:
            row = con.execute("SELECT execution FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return Execution.model_validate_json(row[0]) if row and row[0] else None

    def journal(self, proposal_id: str | None = None) -> list[dict[str, Any]]:
        with self._tx() as con:
            sql = "SELECT seq, proposal_id, sim_ts, from_state, to_state, detail FROM journal"
            rows = (
                con.execute(sql + " WHERE proposal_id = ? ORDER BY seq", (proposal_id,))
                if proposal_id
                else con.execute(sql + " ORDER BY seq")
            ).fetchall()
        keys = ("seq", "proposal_id", "sim_ts", "from_state", "to_state", "detail")
        return [dict(zip(keys, r, strict=True)) | {"detail": json.loads(r[5])} for r in rows]

    # ------------------------------------------------------------------ writes

    def insert(
        self, identity: str, make: Any, sim_ts: datetime, receipts: list[tuple[str, Receipt]]
    ) -> tuple[ProposalView, bool]:
        """Create the proposal `make(seq) -> ProposalView` unless one with this identity exists.

        Returns (proposal, created). The id is allocated and `receipts` ((world revision, receipt), stored as
        e1, e2, ... in order, which `make` may cite) are written inside the same transaction.
        """
        with self._tx() as con:
            found = con.execute(
                "SELECT frozen, state, decision, effect FROM proposals WHERE identity = ?", (identity,)
            ).fetchone()
            if found:
                return self._view(found), False
            seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM proposals").fetchone()[0]
            view: ProposalView = make(seq)
            frozen = view.model_copy(update={"state": "AWAIT_OPERATOR", "decision": None, "effect": None})
            con.execute(
                "INSERT INTO proposals (id, seq, identity, digest, frozen, state) VALUES (?, ?, ?, ?, ?, ?)",
                (view.id, seq, identity, view.digest, frozen.model_dump_json(), "AWAIT_OPERATOR"),
            )
            for n, (revision, receipt) in enumerate(receipts, start=1):
                con.execute(
                    "INSERT INTO receipts (proposal_id, world_revision, receipt_id, body) VALUES (?, ?, ?, ?)",
                    (view.id, revision, f"e{n}", receipt.model_copy(update={"id": f"e{n}"}).model_dump_json()),
                )
            self._journal(con, view.id, sim_ts, None, "AWAIT_OPERATOR", {"digest": view.digest})
            return frozen, True

    def transition(
        self,
        proposal_id: str,
        from_states: set[str],
        to_state: str,
        sim_ts: datetime | None,
        *,
        decision: Decision | None = None,
        decision_key: str | None = None,
        execution: Execution | None = None,
        effect: EffectResult | None = None,
        detail: dict[str, Any] | None = None,
    ) -> ProposalView | None:
        """Move from one of `from_states` to `to_state` atomically. None when the state was not in `from_states`."""
        with self._tx() as con:
            row = con.execute("SELECT state FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            if row is None or row[0] not in from_states:
                return None
            sets, args = ["state = ?"], [to_state]
            for column, value in (
                ("decision", decision),
                ("execution", execution),
                ("effect", effect),
            ):
                if value is not None:
                    sets.append(f"{column} = ?")
                    args.append(value.model_dump_json())
            if decision_key is not None:
                sets.append("decision_key = ?")
                args.append(decision_key)
            con.execute(f"UPDATE proposals SET {', '.join(sets)} WHERE id = ?", (*args, proposal_id))
            self._journal(con, proposal_id, sim_ts, row[0], to_state, detail or {})
            found = con.execute(
                "SELECT frozen, state, decision, effect FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            return self._view(found)

    def set_execution(self, proposal_id: str, execution: Execution) -> None:
        with self._tx() as con:
            con.execute("UPDATE proposals SET execution = ? WHERE id = ?", (execution.model_dump_json(), proposal_id))

    @staticmethod
    def _journal(
        con: sqlite3.Connection,
        proposal_id: str,
        sim_ts: datetime | None,
        from_state: str | None,
        to_state: str,
        detail: dict[str, Any],
    ) -> None:
        con.execute(
            "INSERT INTO journal (proposal_id, sim_ts, from_state, to_state, detail) VALUES (?, ?, ?, ?, ?)",
            (
                proposal_id,
                sim_ts.isoformat() if sim_ts else None,
                from_state,
                to_state,
                json.dumps(detail, sort_keys=True, default=str),
            ),
        )

    # ------------------------------------------------------------------ receipts

    def add_receipt(self, proposal_id: str, world_revision: str, receipt: Receipt) -> ReceiptLink:
        """Store a receipt under the next free id 'e<n>' of this proposal. Returns its qualified link."""
        with self._tx() as con:
            n = con.execute("SELECT COUNT(*) FROM receipts WHERE proposal_id = ?", (proposal_id,)).fetchone()[0]
            rid = f"e{n + 1}"
            body = receipt.model_copy(update={"id": rid})
            con.execute(
                "INSERT INTO receipts (proposal_id, world_revision, receipt_id, body) VALUES (?, ?, ?, ?)",
                (proposal_id, world_revision, rid, body.model_dump_json()),
            )
        return ReceiptLink(run_id=proposal_id, world_revision=world_revision, receipt_id=rid)

    def receipt(self, link: ReceiptLink) -> Receipt | None:
        with self._tx() as con:
            row = con.execute(
                "SELECT body FROM receipts WHERE proposal_id = ? AND world_revision = ? AND receipt_id = ?",
                (link.run_id, link.world_revision, link.receipt_id),
            ).fetchone()
        return Receipt.model_validate_json(row[0]) if row else None
