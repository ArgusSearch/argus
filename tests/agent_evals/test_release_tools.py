from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.agent_eval.bench_gate import validate_scorecard
from scripts.agent_eval.bundle import canonical_json, read_bundle, seal

from argus.agent.examples import PROPOSAL
from argus.contracts.events import Event, TickPayload
from argus.graph.store import load_seed_graph
from argus.semantic.runner import canonical_hash
from bench.scorecard import Scorecard

WORKTREE = Path(__file__).resolve().parents[2]
CHECKED_AT = datetime(2026, 11, 20, 8)
LINK = {"run_id": "run_0001", "world_revision": "factual", "receipt_id": "r1"}
LINK_KEY = "run_0001/factual/r1"


def write_json(path: Path, document: Any) -> None:
    path.write_bytes(canonical_json(document) + b"\n")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_bytes(b"".join(canonical_json(record) + b"\n" for record in records))


def tick(seq: int) -> dict[str, Any]:
    return Event.make(
        seq,
        CHECKED_AT,
        TickPayload(
            as_of=CHECKED_AT,
            hour=CHECKED_AT,
            freshness=[],
            scored_nodes=[],
            pending_nodes=[],
            open_incidents=0,
        ),
    ).model_dump(mode="json")


def proof(receipt_id: str) -> dict[str, Any]:
    return {
        "receipt": {
            "id": receipt_id,
            "sql": "SELECT .83 AS ratio",
            "as_of": CHECKED_AT.isoformat(),
            "result_hash": canonical_hash([(0.83,)]),
            "rows": 1,
            "ms": 1,
        },
        "columns": ["ratio"],
        "rows": [[0.83]],
        "verified_at_capture": True,
    }


def activity(seq: int, kind: str, actor: str = "host") -> dict[str, Any]:
    return {
        "seq": seq,
        "run_id": "run_0001",
        "kind": kind,
        "action_id": "act_0001",
        "actor": actor,
        "sim_ts": CHECKED_AT.isoformat(),
        "stage": "ACT",
    }


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    """Minimal synthetic S4 capture to exercise sealing and refusal paths."""
    write_json(
        tmp_path / "manifest.json",
        {
            "schema_version": 1,
            "provenance": "synthetic_test",
            "source_commit": "1" * 40,
            "scenario": "s4",
            "seed": 1,
            "interface_version": "agent-types/1",
            "prompt_sha": "2" * 64,
            "tools_sha": "3" * 64,
            "models": ["test-model"],
            "world": {"world_start": CHECKED_AT.isoformat()},
        },
    )
    write_json(
        tmp_path / "graph.json",
        load_seed_graph().model_dump(mode="json"),
    )
    write_jsonl(
        tmp_path / "turns.jsonl",
        [
            {
                "key": "investigate:an_0001:1",
                "request_sha": "4" * 64,
                "response": {
                    "model": "test-model",
                    "content": [{"type": "text", "text": "Ready to check"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 12},
                },
            },
        ],
    )
    write_jsonl(tmp_path / "events.jsonl", [tick(1)])
    write_jsonl(tmp_path / "ask.jsonl", [])
    write_json(tmp_path / "receipts.json", {LINK_KEY: proof("r1")})
    proposal = PROPOSAL.model_dump(mode="json") | {"evidence_refs": [LINK]}
    write_json(tmp_path / "actions.json", [proposal])
    write_jsonl(tmp_path / "activity.jsonl", [activity(1, "action_proposed")])
    for branch, state in (("approve", "VERIFIED"), ("deny", "DENIED")):
        path = tmp_path / branch
        path.mkdir()
        write_jsonl(path / "events.jsonl", [tick(2)])
        records = [activity(2, "action_decided", "operator")]
        result = proposal | {
            "state": state,
            "decision": {"decision": branch, "principal": "test-operator", "at": CHECKED_AT.isoformat()},
        }
        if branch == "approve":
            records.append(activity(3, "action_applied"))
            twin = LINK | {"receipt_id": "r2", "world_revision": "untouched"}
            result["effect"] = {
                "state": "VERIFIED",
                "checked_at": CHECKED_AT.isoformat(),
                "summary": "Treated and untreated pacing compared",
                "receipt_refs": [LINK, twin],
            }
            write_json(path / "receipts.json", {"run_0001/untouched/r2": proof("r2")})
        write_jsonl(path / "activity.jsonl", records)
        write_json(path / "actions.json", [result])
    return tmp_path


def test_seal_requires_independent_pin_and_preserves_provenance(staging: Path) -> None:
    sealed = seal(staging)
    first_pin = sealed.manifest.bundle_sha
    assert read_bundle(staging, expected_digest=first_pin, require_live=False) == sealed
    with pytest.raises(ValueError, match="provenance"):
        read_bundle(staging, expected_digest=first_pin)
    (staging / "ask.jsonl").write_text("\n")
    with pytest.raises(ValueError, match="artifacts"):
        read_bundle(staging, expected_digest=first_pin, require_live=False)
    assert seal(staging).manifest.bundle_sha != first_pin
    with pytest.raises(ValueError, match="expected pin"):
        read_bundle(staging, expected_digest=first_pin, require_live=False)


def test_seal_rejects_missing_approval(staging: Path) -> None:
    original = (staging / "manifest.json").read_bytes()
    write_jsonl(staging / "approve" / "activity.jsonl", [activity(3, "action_applied")])
    with pytest.raises(ValueError, match="operator decision"):
        seal(staging)
    assert (staging / "manifest.json").read_bytes() == original


def test_seal_rejects_valid_receipt_from_wrong_run(staging: Path) -> None:
    write_json(staging / "receipts.json", {"another_run/factual/r1": proof("r1")})
    with pytest.raises(ValueError, match="missing qualified receipt"):
        seal(staging)


def test_seal_rejects_corrupt_evidence(staging: Path) -> None:
    wrong_value = proof("r1") | {"rows": [[0.99]]}
    write_json(staging / "receipts.json", {LINK_KEY: wrong_value})
    with pytest.raises(ValueError, match="rows do not match result hash"):
        seal(staging)


def test_seal_rejects_unindexed_artifacts_and_credentials(staging: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extra = staging / "raw-provider.json"
    write_json(extra, {})
    with pytest.raises(ValueError, match="undeclared"):
        seal(staging)
    extra.unlink()
    sample = "example-provider-credential"
    monkeypatch.setenv("TEST_API_KEY", sample)
    turns = [json.loads((staging / "turns.jsonl").read_bytes())]
    turns[0]["response"]["content"][0]["text"] = sample
    write_jsonl(staging / "turns.jsonl", turns)
    with pytest.raises(ValueError, match="credential-like") as failure:
        seal(staging)
    assert sample not in str(failure.value)


def test_bench_gate_ignores_aggregate_pass_when_a_case_fails() -> None:
    card = Scorecard.model_validate_json((WORKTREE / "web/src/views/fixtures/scorecard.sample.json").read_bytes())
    validate_scorecard(card)
    failed = next(run for run in card.runs if run.agent == "argus" and run.scenario == "s1")
    failed.false_alarms.append("spurious-page")
    with pytest.raises(ValueError, match=failed.case):
        validate_scorecard(card)
