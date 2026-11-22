"""Admission, metering and the last live investigation for the public origin."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException, Request

from argus.agent.board import run_of
from argus.agent.openai_provider import API, OpenAIClient
from argus.agent.provider import (
    OPENAI_ASTRA,
    OPENAI_SOL,
    AgentModels,
    ProviderUnavailable,
    SpendLedger,
    price,
    usage_record,
)
from argus.agent.types import LlmClient, LlmRequest, LlmResponse
from argus.api.sources import LiveSource
from argus.contracts.findings import Incident
from argus.remediation.api import OperatorGate, is_local

SESSION_HOUR = 4
IP_HOUR = 12
WATCHER_HOUR = 12
MAX_INPUT_TOKENS = 48_000
MAX_OUTPUT_TOKENS = 3_000
MAX_TURNS = {"ask": 6, "investigate": 8, "critic": 3}
TOKEN_FRAMING_ALLOWANCE = 4096
MIN_AVAILABLE_USD = 0.15
DAY = 86_400
BUDGET_MESSAGE = (
    "The remaining budget cannot cover another live investigation. The daily allowance resets at midnight UTC."
)
UNAVAILABLE = "Live investigations are temporarily unavailable."
log = logging.getLogger(__name__)


def public_provider(limits: PublicLimits, key_file: Path | None) -> tuple[LlmClient, AgentModels]:
    if os.environ.get("ARGUS_DISABLE_PROVIDER") == "1" or os.environ.get("ARGUS_PROVIDER", "openai") != "openai":
        raise ProviderUnavailable(UNAVAILABLE)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and key_file is not None:
        try:
            with key_file.open() as secret:
                if os.fstat(secret.fileno()).st_mode & 0o077:
                    raise ProviderUnavailable(UNAVAILABLE)
                key = secret.read().strip()
        except OSError:
            raise ProviderUnavailable(UNAVAILABLE) from None
    if not key:
        raise ProviderUnavailable(UNAVAILABLE)

    base_url = os.environ.get("ARGUS_PUBLIC_OPENAI_BASE_URL", API)
    url = urlsplit(base_url)
    if base_url != API and (url.scheme != "http" or not is_local(url.hostname) or url.username or url.password):
        raise ProviderUnavailable(UNAVAILABLE)
    # An uncertain response may already have been billed, so the public client never retries a POST.
    client = OpenAIClient(key=key, base_url=base_url, timeout=25, max_retries=0)
    return MeteredClient(client, limits), AgentModels.openai()


class PublicLimits:
    def __init__(self, directory: Path, gate: OperatorGate) -> None:
        daily_usd = float(os.environ.get("ARGUS_PUBLIC_DAILY_USD", "5.00"))
        if not math.isfinite(daily_usd) or daily_usd < 0:
            raise ValueError("ARGUS_PUBLIC_DAILY_USD must be a finite, non-negative amount")
        self.daily_usd = daily_usd
        self.gate = gate
        self._ask_slot = threading.BoundedSemaphore()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = directory / "public.sqlite3"
        ledger_path = Path(os.environ.get("ARGUS_SPEND_LEDGER", str(directory / "spend.jsonl"))).expanduser()
        self.ledger = SpendLedger(ledger_path, durable=True)
        self.ledger_path = ledger_path
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS holds (id TEXT PRIMARY KEY, at INTEGER, usd REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS attempts (at INTEGER, session TEXT, peer TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS archive (id INTEGER PRIMARY KEY, investigation TEXT)")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.db)) as db, db:
            # The hold and the cost-ledger append are serialized across both callers and origin processes.
            db.execute("BEGIN IMMEDIATE")
            yield db

    def _usage(self, db: sqlite3.Connection, now: int) -> tuple[float, float]:
        day = now - now % DAY
        spent = 0.0
        try:
            with self.ledger_path.open() as ledger:
                for line in ledger:
                    if line.strip():
                        row = json.loads(line)
                        if row.get("task") == "argus-agent" and day <= int(row["ts"]) < day + DAY:
                            usd = float(row["usd"])
                            if not math.isfinite(usd) or usd < 0:
                                raise ValueError("Invalid cost")
                            spent += usd
        except FileNotFoundError:
            pass
        # Carry uncertain charges through the following UTC day to cover requests crossing midnight.
        db.execute("DELETE FROM holds WHERE at < ?", (day - DAY,))
        held = float(db.execute("SELECT COALESCE(SUM(usd), 0) FROM holds").fetchone()[0])
        return spent, held

    def _require_budget(self, db: sqlite3.Connection, now: int, usd: float) -> None:
        spent, held = self._usage(db, now)
        if self.daily_usd - spent - held < max(MIN_AVAILABLE_USD, usd):
            raise ProviderUnavailable(BUDGET_MESSAGE)

    @staticmethod
    def _attempts(db: sqlite3.Connection, *, session: str | None = None, peer: str | None = None) -> int:
        return int(
            db.execute("SELECT COUNT(*) FROM attempts WHERE session = ? OR peer = ?", (session, peer)).fetchone()[0]
        )

    def admit_ask(self, request: Request) -> str:
        owner = self.gate.require_session(request)
        peer = (
            getattr(request.state, "public_peer", None)
            or (request.client.host if request.client else None)
            or "unknown"
        )
        peer_key = hashlib.sha256(peer.encode()).hexdigest()
        now = int(time.time())
        try:
            with self.transaction() as db:
                self._require_budget(db, now, 0)
                db.execute("DELETE FROM attempts WHERE at <= ?", (now - 3600,))
                if self._attempts(db, session=owner) >= SESSION_HOUR:
                    raise HTTPException(
                        429, f"This session reached its limit of {SESSION_HOUR} investigations per hour."
                    )
                if self._attempts(db, peer=peer_key) >= IP_HOUR:
                    raise HTTPException(429, f"This connection reached its limit of {IP_HOUR} investigations per hour.")
                db.execute("INSERT INTO attempts VALUES (?, ?, ?)", (now, owner, peer_key))
        except ProviderUnavailable as exc:
            raise HTTPException(429, str(exc)) from None
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            raise HTTPException(503, UNAVAILABLE) from None
        return owner

    @contextmanager
    def ask_slot(self) -> Iterator[None]:
        if not self._ask_slot.acquire(blocking=False):
            raise HTTPException(
                429, "Another Ask investigation is running. Try again shortly.", headers={"Retry-After": "10"}
            )
        try:
            yield
        finally:
            self._ask_slot.release()

    def reserve(self, usd: float, *, starts_investigation: bool) -> str:
        now = int(time.time())
        reservation = uuid4().hex
        with self.transaction() as db:
            self._require_budget(db, now, usd)
            if starts_investigation:
                db.execute("DELETE FROM attempts WHERE at <= ?", (now - 3600,))
                if self._attempts(db, session="watcher") >= WATCHER_HOUR:
                    raise ProviderUnavailable("The watcher reached its hourly limit for live investigations.")
                db.execute("INSERT INTO attempts VALUES (?, ?, ?)", (now, "watcher", ""))
            db.execute("INSERT INTO holds VALUES (?, ?, ?)", (reservation, now, usd))
        return reservation

    def settle(self, reservation: str, kind: str, response: LlmResponse, model: str, maximum: float) -> None:
        if not response.usage:
            return
        billed = response.model_copy(update={"model": model})
        charge = usage_record(reservation, 1, billed, 0)
        if charge.usd is None or charge.usd < 0:
            return
        rounded = charge.model_copy(update={"usd": math.ceil(charge.usd * 1_000_000) / 1_000_000})
        with self.transaction() as db:
            self.ledger.append_run(reservation, f"public-{kind}", [rounded])
            db.execute("DELETE FROM holds WHERE id = ?", (reservation,))
            if charge.usd > maximum:
                # Fail closed for the rest of the day if the provider exceeds the metering bound.
                db.execute("INSERT INTO holds VALUES (?, ?, ?)", (uuid4().hex, int(time.time()), self.daily_usd))

    def status(self) -> dict[str, Any]:
        try:
            now = int(time.time())
            with self.transaction() as db:
                spent, held = self._usage(db, now)
                archive = db.execute("SELECT investigation FROM archive WHERE id = 1").fetchone()
            exhausted = self.daily_usd - spent - held < MIN_AVAILABLE_USD
            return {
                "daily_usd": self.daily_usd,
                "spent_today_usd": round(spent, 6),
                "session_hour": SESSION_HOUR,
                "ip_hour": IP_HOUR,
                "watcher_hour": WATCHER_HOUR,
                "input_tokens": MAX_INPUT_TOKENS,
                "output_tokens": MAX_OUTPUT_TOKENS,
                "turns": MAX_TURNS,
                "message": BUDGET_MESSAGE if exhausted else None,
                "stored_investigation": json.loads(archive[0]) if exhausted and archive else None,
            }
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            return {"message": UNAVAILABLE}

    def archive(self, source: LiveSource, incident: Incident) -> None:
        journal = source.agent.journal
        with journal.lock:
            run_id = run_of(incident, journal.records)
            run = journal.runs.get(run_id) if run_id is not None else None
        if not run or run.mode != "live" or run.status != "done" or run.llm_calls == 0:
            return
        investigation = json.dumps(
            {
                "stored_at": datetime.now(UTC).isoformat(),
                "title": incident.title,
                "report": source.report(incident.id),
            }
        )
        try:
            with self.transaction() as db:
                db.execute("INSERT OR REPLACE INTO archive VALUES (1, ?)", (investigation,))
        except (OSError, sqlite3.Error):
            log.warning("Could not save the latest public investigation")


class MeteredClient:
    def __init__(self, client: OpenAIClient, limits: PublicLimits) -> None:
        self.client = client
        self.limits = limits
        self._investigation: str | None = None

    def create(self, request: LlmRequest) -> LlmResponse:
        kind, subject, turn_text = request.key.split(":", 2)
        turn = int(turn_text)
        starting = kind == "investigate" and turn == 1
        if starting:
            self._investigation = None
        if kind == "critic" and self._investigation != subject:
            raise ProviderUnavailable("The investigation did not start a live model session.")
        if turn < 1 or turn > MAX_TURNS[kind] or request.max_tokens > MAX_OUTPUT_TOKENS:
            raise ProviderUnavailable("The investigation reached its model turn or output limit.")
        model = OPENAI_ASTRA if kind == "critic" else OPENAI_SOL
        if request.model != model:
            raise ProviderUnavailable(UNAVAILABLE)
        try:
            wire = json.dumps(self.client.request_body(request), ensure_ascii=False, separators=(",", ":")).encode()
            # Count bytes rather than words, and reserve additional tokens for provider framing.
            input_tokens = len(wire) + TOKEN_FRAMING_ALLOWANCE
            if input_tokens > MAX_INPUT_TOKENS:
                raise ProviderUnavailable("The investigation reached its model input limit.")
            maximum = price(model, {"cache_creation_input_tokens": input_tokens, "output_tokens": request.max_tokens})
            if maximum is None:
                raise ProviderUnavailable(UNAVAILABLE)
            reservation = self.limits.reserve(maximum, starts_investigation=starting)
            try:
                response = self.client.create(request)
            except ProviderUnavailable as exc:
                if exc.response is not None:
                    self.limits.settle(reservation, kind, exc.response, model, maximum)
                raise
            self.limits.settle(reservation, kind, response, model, maximum)
            if starting:
                self._investigation = subject
            return response
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            raise ProviderUnavailable(UNAVAILABLE) from None
