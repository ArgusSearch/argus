"""The agent journal: the activity log, run summaries and provider usage of one stream (an `ActivitySink`).

Append-only and thread-safe. `seq` is assigned here, strictly increasing. With a path it also writes
`activity.jsonl` as it goes, so a crash leaves the log up to the last record.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from argus.agent.types import ActivityKind, ActivityRecord, Role, RunSummary, Stage, UsageRecord

SKEPTIC_TOOLS = frozenset({"holdout_check", "placebo_test", "check_freshness", "check_identities"})
MARKET_TOOLS = frozenset({"market_control", "check_control_group"})


def role_of(record: ActivityRecord) -> Role:
    """The avatar a record shows when its writer did not name one."""
    if record.kind == "watch":
        return "watcher"
    if record.actor == "operator" or record.kind.startswith("action_"):
        return "operator"
    if record.kind in ("report", "chat_answer", "chat_question") or record.stage == "ASK":
        return "narrator"
    if record.tool in MARKET_TOOLS:
        return "market"
    if record.tool in SKEPTIC_TOOLS or record.kind in ("gate", "rejected", "budget", "fallback"):
        return "skeptic"
    return "detective"


class Journal:
    def __init__(self, stream: str = "local", path: Path | None = None) -> None:
        self.stream = stream
        self.path = path
        self.records: list[ActivityRecord] = []
        self.runs: dict[str, RunSummary] = {}
        self.usage: list[UsageRecord] = []
        self.lock = threading.Lock()

    # ActivitySink
    def emit(self, record: ActivityRecord) -> None:
        with self.lock:
            record = record.model_copy(update={"seq": len(self.records) + 1, "role": record.role or role_of(record)})
            self.records.append(record)
            if self.path is not None:
                with self.path.open("a") as f:
                    f.write(record.model_dump_json() + "\n")

    def add(
        self, kind: ActivityKind, stage: Stage, sim_ts: datetime, run_id: str | None, actor: str = "host", **fields: Any
    ) -> None:
        self.emit(ActivityRecord(seq=0, run_id=run_id, sim_ts=sim_ts, kind=kind, stage=stage, actor=actor, **fields))  # type: ignore[arg-type]

    def new_run_id(self) -> str:
        with self.lock:
            return f"run_{len(self.runs) + 1:04d}"

    def start_run(self, summary: RunSummary) -> None:
        with self.lock:
            self.runs[summary.run_id] = summary

    def finish_run(self, run_id: str, **update: Any) -> RunSummary:
        with self.lock:
            run = self.runs[run_id].model_copy(update=update)
            self.runs[run_id] = run
            return run

    def add_usage(self, usage: UsageRecord) -> None:
        with self.lock:
            self.usage.append(usage)

    def since(self, seq: int) -> list[ActivityRecord]:
        with self.lock:
            return [r for r in self.records if r.seq > seq]
