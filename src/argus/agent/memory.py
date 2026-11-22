"""Simulated-time case memory for the v2 proposal policy and experience packet."""

from __future__ import annotations

import fcntl
import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from argus.agent.types import CaseMemory, CaseNote, PolicyName
from argus.contracts.findings import Verdict

_LABEL = re.compile(r"[A-Za-z_][A-Za-z_:-]*\Z")
_ID = re.compile(r"[A-Za-z0-9_:.=-]+(?:[|,][A-Za-z0-9_:.=-]+)*\Z")


def _safe_note(note: CaseNote) -> CaseNote:
    # Digits in canonical timestamps, ids, fingerprints and versioned event refs are structural.
    # There is no prose or numeric finding in a note, and labels must be numbers-free.
    for value in (note.root_node, note.cause_kind, note.playbook_id, *note.deciding_checks, *note.segment_dims):
        if value is not None and not _LABEL.fullmatch(value):
            raise ValueError("case notes require numbers-free labels")
    for value in (note.case_id, note.fingerprint, note.cause_ref):
        if value is not None and not _ID.fullmatch(value):
            raise ValueError("case notes require structured identifiers")
    if note.verdict not in {verdict.value for verdict in Verdict}:
        raise ValueError("case notes require a known verdict")
    return note


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo is None else ts.astimezone(UTC).replace(tzinfo=None)


class JsonlCaseMemory:
    """Append decided cases to a file shared across simulated worlds."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def remember(self, note: CaseNote) -> None:
        line = _safe_note(CaseNote.model_validate(note.model_dump())).model_dump_json().encode() + b"\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+b") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            # A seeded JSONL file may have an unterminated final record.
            if file.seek(0, os.SEEK_END):
                file.seek(-1, os.SEEK_END)
                if file.read(1) != b"\n":
                    line = b"\n" + line
            file.write(line)

    def recall(
        self, *, root_node: str, segment: dict[str, str], cause_kind: str | None, as_of: datetime, limit: int = 3
    ) -> list[CaseNote]:
        if limit <= 0:
            return []
        ranked: list[tuple[int, datetime, str, CaseNote]] = []
        cutoff = _utc(as_of)
        try:
            with self.path.open(encoding="utf-8") as file:
                fcntl.flock(file, fcntl.LOCK_SH)
                for line in file:
                    if not line.strip():
                        continue
                    note = _safe_note(CaseNote.model_validate_json(line))
                    time = _utc(note.sim_ts)
                    if time >= cutoff:
                        continue
                    score = 3 * (note.root_node == root_node) + 2 * (
                        cause_kind is not None and note.cause_kind == cause_kind
                    )
                    score += bool(segment.keys() & set(note.segment_dims))
                    if score:
                        ranked.append((score, time, note.model_dump_json(), note))
        except FileNotFoundError:
            return []
        ranked.sort(key=lambda entry: entry[:3], reverse=True)
        return [note for _, _, _, note in ranked[:limit]]


def configured_memory() -> CaseMemory | None:
    """Open the configured store only in the v2 profile with memory enabled."""
    if os.environ.get("ARGUS_AGENT_PROFILE") != "v2":
        return None
    features = os.environ.get("ARGUS_AGENT_FEATURES")
    if features is not None and "memory" not in {value.strip() for value in features.split(",")}:
        return None
    path = os.environ.get("ARGUS_AGENT_MEMORY")
    return JsonlCaseMemory(path) if path else None


def cause_kind_for(cause_ref: str | None) -> str | None:
    if cause_ref and cause_ref.startswith("dep_"):
        service, separator, _ = cause_ref[4:].partition("_")
        if separator:
            return f"deploy:{service}"
    if cause_ref and cause_ref.startswith("pacer_"):
        return "deploy:ad-pacer"
    return None


def matching_precedent(
    notes: Sequence[CaseNote], playbook_id: str, cause_ref: str | None
) -> tuple[PolicyName, CaseNote | None]:
    relevant = [note for note in notes if note.playbook_id == playbook_id]
    exact = [note for note in relevant if cause_ref is not None and note.cause_ref == cause_ref]
    cause_kind = cause_kind_for(cause_ref)
    family = [note for note in relevant if note in exact or (cause_kind is not None and note.cause_kind == cause_kind)]
    for note in exact:
        if note.decision == "deny":
            return "suppress_denied", note
    for note in family:
        if note.decision == "approve" and note.effect == "NO_EFFECT":
            return "suppress_no_effect", note
    for note in family:
        if note.decision == "approve" and note.effect == "VERIFIED":
            return "propose_with_precedent", note
    return "propose", next((note for note in family if note.decision == "deny"), None)


def proposal_policy(notes: Sequence[CaseNote], playbook_id: str, cause_ref: str | None) -> PolicyName:
    """Return the deterministic policy for an independently qualified case."""
    return matching_precedent(notes, playbook_id, cause_ref)[0]
