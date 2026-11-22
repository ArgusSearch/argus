"""Verify the shipped v1 bytes and require two independent cold runs for each v2 pin."""

from __future__ import annotations

import json

import pytest
from scripts.agent_eval.bundle import canonical_json, sha256
from scripts.agent_eval.capture_cassette import verify_cassette
from scripts.agent_eval.capture_presentation import verify_presentation
from test_intel_board import FIXTURES
from test_runtime_gates import world_case as world_case

from argus.agent.investigate import tool_specs
from argus.agent.prompts import SELECT
from argus.agent.types import ActivityRecord
from argus.contracts.findings import Incident


@pytest.mark.e2e
@pytest.mark.parametrize("scenario", ("s1", "s4"))
def test_e27_v1_cassette_is_unchanged(world_case, monkeypatch, tmp_path, scenario):
    monkeypatch.setenv("ARGUS_AGENT_PROFILE", "v1")
    spend = tmp_path / "replay-spend.jsonl"
    monkeypatch.setenv("ARGUS_SPEND_LEDGER", str(spend))
    case = world_case(scenario)
    root = FIXTURES / "v1" / "cassettes"
    digest = json.loads((root / "accepted.json").read_bytes())[scenario]
    bundle = verify_cassette(root / scenario, digest, case.world)
    assert bundle.manifest.profile is None
    assert bundle.manifest.prompt_sha == sha256(SELECT.encode())
    assert bundle.manifest.tools_sha == sha256(canonical_json(tool_specs()))
    assert not spend.exists() or spend.read_bytes() == b""


@pytest.mark.e2e
@pytest.mark.parametrize("scenario", ("s1", "s4"))
def test_e27_v2_presentation_replays_cold_twice(scenario, monkeypatch, tmp_path):
    root = FIXTURES / "v2"
    digest = json.loads((root / "accepted.json").read_bytes()).get(scenario)
    assert digest, f"v2/{scenario} needs a retained live capture and its external pin"
    from argus.agent.board import build_board

    from argus.demo.agent import load_agent_timeline

    spend = tmp_path / "replay-spend.jsonl"
    monkeypatch.setenv("ARGUS_SPEND_LEDGER", str(spend))
    monkeypatch.setenv("ARGUS_DEMO_BUNDLE", str(root / scenario))
    monkeypatch.setenv("ARGUS_DEMO_BUNDLE_SHA", digest)
    timeline = load_agent_timeline(scenario)
    assert timeline.scenario == scenario and timeline.bundle.manifest.bundle_sha == digest
    board_bytes = []
    for _ in range(2):
        bundle = verify_presentation(root / scenario, digest)
        assert (bundle.manifest.scenario, bundle.manifest.seed, bundle.manifest.profile) == (scenario, 1, "v2")
        assert {"critic", "sql", "hypotheses"} <= set(bundle.manifest.features or [])
        (incident,) = [Incident.model_validate(row) for row in bundle.documents["incidents.json"]]
        records = [ActivityRecord.model_validate(row) for row in bundle.documents["activity.jsonl"]]
        board = build_board(records, incident.findings, None)
        assert board.profile == "v2"
        board_bytes.append(canonical_json(board.model_dump(mode="json")))
    assert board_bytes[0] == board_bytes[1]
    assert not spend.exists() or spend.read_bytes() == b""
