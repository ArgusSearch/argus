"""Sealed envelope: commit to the hidden truth before Argus runs, reveal and verify it afterwards.

The commitment is `sha256:` + hex(SHA-256(nonce + "\\n" + payload)), where `payload` is the canonical JSON
of `truth.duckdb` (world params plus every injected event, keys sorted, timestamps in ISO format) and
`nonce` is a fresh random hex string. Publishing the commitment before the run and the nonce plus payload
after it proves the truth was fixed in advance: anyone can recompute the hash, even in a phone browser
(`crypto.subtle.digest("SHA-256", ...)` over the same UTF-8 string).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from mockmart.truth import read_truth


def _json_default(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def canonical_truth(truth_path: Path) -> str:
    """Canonical JSON of a truth file. Byte-identical for the same scenario, seed and code."""
    con = duckdb.connect(str(truth_path), read_only=True)
    try:
        params = dict(con.execute("SELECT key, value FROM world_params ORDER BY key").fetchall())
    finally:
        con.close()
    events = sorted(read_truth(truth_path), key=lambda e: e["event_id"])
    doc = {"world_params": params, "events": events}
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=_json_default)


def commitment_of(nonce: str, payload: str) -> str:
    return "sha256:" + hashlib.sha256(f"{nonce}\n{payload}".encode()).hexdigest()


@dataclass(frozen=True)
class Envelope:
    """The sealed truth. Only `commitment` may be shown before the reveal."""

    commitment: str
    nonce: str
    payload: str

    def reveal(self) -> dict[str, Any]:
        return {"commitment": self.commitment, "nonce": self.nonce, "payload": self.payload}


def seal(truth_path: Path, nonce: str | None = None) -> Envelope:
    payload = canonical_truth(truth_path)
    nonce = nonce if nonce is not None else secrets.token_hex(16)
    return Envelope(commitment=commitment_of(nonce, payload), nonce=nonce, payload=payload)


def verify(commitment: str, nonce: str, payload: str) -> bool:
    return secrets.compare_digest(commitment, commitment_of(nonce, payload))


def bench_commitment(case_commitments: dict[str, str]) -> str:
    """One hash over every case of a bench run, printed before any agent starts."""
    lines = "\n".join(f"{case}={c}" for case, c in sorted(case_commitments.items()))
    return "sha256:" + hashlib.sha256(lines.encode()).hexdigest()
