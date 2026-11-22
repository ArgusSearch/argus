from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_eval.offline_report import CASES, summarize
from scripts.agent_eval.qualify import Counterexample, Trial, check_usage, score, show_quality
from scripts.agent_eval.text_review import Sample, assess

from argus.agent.examples import OBSERVATION, RUN, USAGE
from argus.agent.fake import FakeLlmClient, tool_use
from argus.agent.provider import SYNTHESIS_MODEL, SpendLedger, usage_record
from argus.agent.types import LlmRequest, LlmResponse


def test_offline_scorecard_rejects_missing_skipped_and_failed_cases(tmp_path: Path) -> None:
    xml = tmp_path / "report.xml"
    xml.write_text(
        "<testsuites><testsuite>"
        '<testcase name="test_e01_scenario[s1]"/>'
        '<testcase name="test_e01_scenario[s4]"><failure message="wrong effect"/></testcase>'
        '<testcase name="test_e02_root"><skipped message="missing recording"/></testcase>'
        '<testcase name="test_e05_predictions"/>'
        "</testsuite></testsuites>"
    )
    report = summarize(xml, "release-sha")
    assert report["required"] == len(CASES) == 17
    assert report["passed"] == 1
    assert report["commit"] == "release-sha"
    assert len(report["scenario_matrix"]) == 18


def test_live_scorecard_keeps_all_unattempted_trials_visible(tmp_path: Path) -> None:
    report = score(tmp_path, "release-sha")
    assert report["live_eligible"] is False
    assert report["changed_observation_passed"] is False
    assert len(report["trials"]) == 18


def test_live_usage_rejects_unknown_price_duplicate_calls_and_wrong_total() -> None:
    response = tool_use("list_events", {}).model_copy(update={"request_id": USAGE.request_id})
    priced = usage_record(RUN.run_id, 1, response, 100)
    assert priced.usd is not None
    run = RUN.model_copy(update={"llm_calls": 1, "usd": round(priced.usd, 6)})
    trial = Trial(scenario="s1", seed=1, trial=1, source_commit="sha", elapsed_seconds=1, runs=[run], usage=[priced])
    assert check_usage(trial) == []
    trial.usage.append(priced.model_copy(update={"usd": None}))
    invalid = check_usage(trial)
    assert "missing or invalid priced usage" in invalid
    assert "duplicated provider call" in invalid
    assert f"usage differs from run {run.run_id}" in invalid


def test_live_adaptivity_needs_a_changed_observation_and_provider_choice() -> None:
    original = tool_use("placebo_test", {}).model_copy(update={"request_id": "original-request"})
    changed = tool_use("market_control", {}).model_copy(update={"request_id": "changed-request"})
    counterexample = Counterexample(
        source_commit="release-sha",
        original_observation=OBSERVATION,
        changed_observation=OBSERVATION.model_copy(update={"outcome": "consistent"}),
        original_response=original,
        changed_response=changed,
    )
    assert counterexample.passed("release-sha")
    assert not counterexample.passed("stale-sha")
    counterexample.changed_response = original.model_copy(update={"request_id": "third-request"})
    assert not counterexample.passed("release-sha")


def test_text_judge_only_scores_prose(tmp_path: Path) -> None:
    text_review = tmp_path / "text-review.json"
    text_review.write_text(
        json.dumps([{"sample": "memo-s1", "what_happened": 5, "why": 5, "alternative": 2, "next_action": 5}])
    )
    review = show_quality(text_review)
    assert review["mean"] == 4.25
    assert review["rubric_passed"] is False
    assert review["below_three"] == ["memo-s1"]


def test_text_judge_has_no_tools_and_records_spend(tmp_path: Path) -> None:
    def review(request: LlmRequest) -> LlmResponse:
        assert request.tools == []
        assert json.loads(request.messages[0]["content"]) == {"prose": "The evidence points to pacing."}
        return LlmResponse(
            model=SYNTHESIS_MODEL,
            content=[{"type": "text", "text": '{"what_happened":5,"why":4,"alternative":3,"next_action":4}'}],
            stop_reason="end_turn",
            usage={"input_tokens": 100, "output_tokens": 20},
        )

    ledger = tmp_path / "qualification-spend.jsonl"
    outcomes = assess(
        [Sample(sample="blind-1", text="The evidence points to pacing.")],
        FakeLlmClient(responder=review),
        SpendLedger(ledger),
    )
    assert outcomes[0].sample == "blind-1" and outcomes[0].what_happened == 5
    assert len(ledger.read_bytes().splitlines()) == 1
