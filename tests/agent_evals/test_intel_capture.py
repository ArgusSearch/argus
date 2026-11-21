"""Verify the v2 manifest binds critic turns and memory to the released evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_eval.bundle import canonical_json, read_bundle, seal, sha256
from test_release_tools import staging as staging


def test_v2_seal_binds_memory_and_critic_turns(staging: Path):
    path = staging / "manifest.json"
    memory = b""
    memory_path = staging / "memory.jsonl"
    memory_path.write_bytes(memory)
    manifest = json.loads(path.read_bytes()) | {
        "profile": "v2",
        "features": ["critic", "memory"],
        "memory_sha": sha256(memory),
    }
    path.write_bytes(canonical_json(manifest))
    raw_turns = staging / "turns.jsonl"
    turn = json.loads(raw_turns.read_bytes().splitlines()[0])
    with raw_turns.open("ab") as f:
        f.write(canonical_json({**turn, "key": "critic:an_eval:1"}) + b"\n")

    bundle = seal(staging)
    assert bundle.manifest.profile == "v2"
    assert bundle.manifest.memory_sha == bundle.manifest.artifacts["memory.jsonl"]
    assert bundle.documents["turns.jsonl"][-1]["key"] == "critic:an_eval:1"
    with pytest.raises(ValueError, match="provenance"):
        read_bundle(staging, expected_digest=bundle.manifest.bundle_sha)

    memory_path.write_bytes(b"\n")
    with pytest.raises(ValueError, match="artifacts"):
        read_bundle(staging, expected_digest=bundle.manifest.bundle_sha, require_live=False)
    with pytest.raises(ValueError, match="memory seed"):
        seal(staging)


def test_v2_qualification_fails_a_missing_retained_cohort(tmp_path):
    from scripts.agent_eval.qualify_intel import score_intelligence

    report = score_intelligence(tmp_path, "1" * 40)
    assert report["profile"] == "v2" and report["live_eligible"] is False
    assert report["pass_power_3"] == {"s1": False, "s4": False}
    trials = report["trials"]
    assert isinstance(trials, list) and len(trials) == 6
    assert all(item["failures"] for item in trials)
