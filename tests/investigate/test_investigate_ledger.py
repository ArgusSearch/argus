"""Hypothesis ledger: typed proposals, outcomes read from tool outputs, deterministic verdicts, budget."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from argus.contracts.findings import Anomaly, EvidenceRef, Window
from argus.contracts.tools import (
    DecomposeFormulaOutput,
    HoldoutCheckOutput,
    MixRateSplitOutput,
    PlaceboTestOutput,
    SegmentSearchOutput,
    ToolOutput,
)
from argus.investigate.ledger import Hypothesis, Ledger, judge, outcome_of
from argus.investigate.planner import PlannerContext, ScriptedPlanner, proposals_from_json

WINDOW = Window(start=datetime(2026, 11, 20, 21), end=datetime(2026, 11, 20, 23))
EVENT = EvidenceRef(
    log="log_provider_status",
    ref="ps_payco_degraded",
    ts=datetime(2026, 11, 20, 20, 58),
    kind="degraded",
    description="PayCo degraded",
    scope={"provider": ["PayCo"]},
)


def holdout_hypothesis(expect: str = "consistent") -> Hypothesis:
    return Hypothesis(
        statement="PayCo degraded caused the drop",
        prediction="the change is confined to PayCo",
        tool="holdout_check",
        input={
            "event": EVENT.model_dump(mode="json"),
            "node": "payment_success_rate",
            "segment": {"provider": "PayCo"},
            "window": WINDOW.model_dump(mode="json"),
        },
        expect=expect,
    )


def holdout_output(result: str) -> HoldoutCheckOutput:
    return HoldoutCheckOutput(summary=result, receipts=["r1"], holdout={}, rel_change=0.0, z=0.0, result=result)


def test_hypothesis_must_name_a_judgeable_c6_tool_with_valid_input_and_outcome() -> None:
    holdout_hypothesis()  # valid
    with pytest.raises(ValidationError, match="unknown tool"):
        Hypothesis(statement="s", prediction="p", tool="run_sql", input={}, expect="x")
    with pytest.raises(ValidationError, match="no judgeable outcome"):
        Hypothesis(statement="s", prediction="p", tool="lag_test", input={"x": "a", "y": "b"}, expect="lagged")
    with pytest.raises(ValidationError):
        Hypothesis(statement="s", prediction="p", tool="holdout_check", input={"node": "orders"}, expect="consistent")
    with pytest.raises(ValidationError, match="outcomes are"):
        holdout_hypothesis(expect="true")
    with pytest.raises(ValidationError, match="factor:<node id>"):
        Hypothesis(
            statement="s",
            prediction="p",
            tool="decompose_formula",
            input={"node": "orders", "window": WINDOW.model_dump(mode="json")},
            expect="sessions",
        )


@pytest.mark.parametrize(
    ("output", "outcome"),
    [
        (holdout_output("consistent"), "consistent"),
        (holdout_output("refuted"), "refuted"),
        (holdout_output("inconclusive"), None),
        (holdout_output("not_applicable"), None),
        (PlaceboTestOutput(summary="", hits=0, weeks=5), "unusual"),
        (PlaceboTestOutput(summary="", hits=1, weeks=5), None),
        (PlaceboTestOutput(summary="", hits=3, weeks=5), "recurring"),
        (PlaceboTestOutput(summary="", hits=0, weeks=0), None),
        (MixRateSplitOutput(summary="", change=-0.01, mix=-0.009, rate=-0.001, rates_flat=True), "mix"),
        (MixRateSplitOutput(summary="", change=-0.01, mix=-0.009, rate=-0.001, rates_flat=False), None),
        (MixRateSplitOutput(summary="", change=-0.01, mix=-0.001, rate=-0.009, rates_flat=False), "rate"),
        (SegmentSearchOutput(summary="", segment={}, explained_share=1.0, path=[]), "diffuse"),
        (SegmentSearchOutput(summary="", segment={"country": "DE"}, explained_share=0.9, path=[]), "localized"),
        (SegmentSearchOutput(summary="", segment={"country": "DE"}, explained_share=0.4, path=[]), None),
    ],
)
def test_outcome_is_read_from_the_tool_output(output: ToolOutput, outcome: str | None) -> None:
    tool = {
        HoldoutCheckOutput: "holdout_check",
        PlaceboTestOutput: "placebo_test",
        MixRateSplitOutput: "mix_rate_split",
        SegmentSearchOutput: "segment_search",
    }[type(output)]
    assert outcome_of(tool, output) == outcome


def test_judge_compares_the_outcome_with_the_expectation() -> None:
    h = holdout_hypothesis()
    assert judge(h, "consistent") == "validated"
    assert judge(h, "refuted") == "refuted"
    assert judge(h, None) == "inconclusive"
    d = Hypothesis(
        statement="payment success carries the drop",
        prediction="payment_success_rate is the dominant factor",
        tool="decompose_formula",
        input={"node": "orders", "window": WINDOW.model_dump(mode="json")},
        expect="factor:payment_success_rate",
    )
    empty = DecomposeFormulaOutput(summary="", node="orders", factors=[], contributions=[], residual=0.0)
    assert outcome_of("decompose_formula", empty) is None
    assert judge(d, "factor:payment_success_rate") == "validated"
    assert judge(d, "factor:sessions") == "refuted"


def test_ledger_enforces_the_budget_and_records_failed_checks_as_inconclusive() -> None:
    ledger = Ledger(budget=2)

    def boom(h: Hypothesis) -> ToolOutput:
        raise RuntimeError("lag_test is lane G")

    first = ledger.test(holdout_hypothesis(), lambda h: holdout_output("refuted"))
    assert first is not None and first[0].status == "refuted" and first[0].receipts == ["r1"]
    second = ledger.test(holdout_hypothesis(), boom)
    assert second is not None and second[0].status == "inconclusive" and "lane G" in second[0].summary
    assert ledger.test(holdout_hypothesis(), lambda h: holdout_output("consistent")) is None
    assert [e.id for e in ledger.entries] == ["h1", "h2"]


def test_llm_proposals_are_validated_and_capped() -> None:
    good = holdout_hypothesis().model_dump(mode="json")
    del good["source"]
    reply = (
        '{"hypotheses": ['
        + ",".join(
            [
                '{"statement": "s", "prediction": "p", "tool": "run_sql", "input": {}, "expect": "x"}',
                '"just text"',
                *([json.dumps(good)] * 4),
            ]
        )
        + "]}"
    )
    accepted, rejected = proposals_from_json(reply, source="planner:llm", limit=3)
    assert len(accepted) == 3
    assert all(h.source == "planner:llm" for h in accepted)
    assert len(rejected) == 3
    assert any("unknown tool" in r for r in rejected)
    nothing, reasons = proposals_from_json("not json", source="planner:llm")
    assert nothing == [] and reasons[0].startswith("not JSON")


def test_scripted_planner_tags_its_proposals() -> None:
    planner = ScriptedPlanner([holdout_hypothesis()], name="replay")
    anomaly = Anomaly(
        id="an_0001",
        node="payment_success_rate",
        direction="down",
        hour=WINDOW.end,
        detected_at=WINDOW.end,
        onset=WINDOW.start,
        observed=0.92,
        expected=0.95,
        band=(0.94, 0.96),
        z=-8.0,
        rule="z_gt_4",
    )
    ctx = PlannerContext(
        anomaly=anomaly,
        focus="payment_success_rate",
        segment={},
        window=WINDOW,
        explained_share=0.5,
        neighbourhood=[],
        edges=[],
        budget=3,
    )
    proposals = planner.propose(ctx)
    assert planner.calls == 1
    assert [h.source for h in proposals] == ["planner:replay"]
    assert "holdout_check" in ctx.tools
