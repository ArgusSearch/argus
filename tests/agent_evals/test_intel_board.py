"""Compare board and chain projections with sealed inputs and independent simulator expectations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_eval.bundle import Bundle, read_bundle
from test_runtime_gates import world_case as world_case

from argus.agent.types import ActivityRecord
from argus.contracts.findings import Incident, Verdict
from argus.runtime.loop import Runtime

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "agent"
SEEDS = (1, 3, 7)
CAUSES = {
    "s1": ("ps_payco_degraded", "payment_success_rate", {"country": "DE", "platform": "android", "provider": "PayCo"}),
    "s4": ("dep_ad-pacer_1.7.0", "pacing_ratio", {}),
}


def pinned(profile: str, scenario: str, *, cassette: bool = False) -> Bundle:
    root = FIXTURES / profile
    if cassette:
        root /= "cassettes"
    pins = json.loads((root / "accepted.json").read_bytes())
    assert pins[scenario], f"{profile}/{scenario} needs a retained live capture and an external pin"
    return read_bundle(root / scenario, expected_digest=pins[scenario], presentation=not cassette)


def stage2(case) -> Runtime:
    runtime = Runtime(case.world)
    try:
        runtime.run()
        assert not runtime.fallbacks
        return runtime
    finally:
        runtime.runner.close()


def match_board(board, incident: Incident, scenario: str) -> None:
    cause, node, segment = CAUSES[scenario]
    root = incident.findings.root
    assert root is not None and root.evidence is not None
    assert (root.evidence.ref, root.node, root.segment) == (cause, node, segment)
    supported = [card for card in board.hypotheses if card.status == "supported"]
    assert [card.subject for card in supported] == [root.evidence.ref]
    assert "open" not in {card.status for card in board.hypotheses}
    assert sum(board.counts.values()) == len(board.hypotheses)
    for alt in incident.findings.ruled_out:
        assert any(
            card.status == ("ruled_out" if alt.result == "refuted" else "inconclusive")
            and (
                card.subject == alt.evidence.ref
                if alt.evidence is not None
                else bool(set(alt.receipts) & {link.receipt_id for check in card.checks for link in check.receipts})
            )
            for card in board.hypotheses
        ), alt
    if scenario == "s1":
        (android,) = [card for card in board.hypotheses if card.subject == "dep_android-app_8.3.0"]
        assert android.status == "ruled_out"
        assert any(check.receipts for check in android.checks)
    assert all(
        any(check.receipts for check in card.checks)
        for card in board.hypotheses
        if card.status not in {"open", "not_tested"}
    )


@pytest.mark.e2e
@pytest.mark.parametrize("scenario", CAUSES)
@pytest.mark.parametrize("seed", (*SEEDS, "v1"))
def test_e18_board_reconciles_cause_and_alternatives(world_case, scenario, seed):
    from argus.agent.board import build_board

    if seed == "v1":
        bundle = pinned("v1", scenario)
        (incident,) = [Incident.model_validate(row) for row in bundle.documents["incidents.json"]]
        records = [ActivityRecord.model_validate(row) for row in bundle.documents["activity.jsonl"]]
        board = build_board(records, incident.findings, None)
        assert all(
            any(key in bundle.documents["receipts.json"] for key in (link.key(), link.receipt_id))
            for card in board.hypotheses
            for check in card.checks
            for link in check.receipts
        )
    else:
        (incident,) = stage2(world_case(scenario, seed)).book.incidents.values()
        board = build_board([], incident.findings, None)
    match_board(board, incident, scenario)


@pytest.mark.e2e
@pytest.mark.parametrize("scenario", ("s2", "s3", "quiet"))
def test_e18_no_supported_event_in_negative_scenarios(world_case, scenario):
    from argus.agent.board import build_board

    runtime = stage2(world_case(scenario))
    assert not runtime.book.incidents
    board = build_board([], None, None)
    assert not any(card.kind == "event" and card.status == "supported" for card in board.hypotheses)
    assert board.chain is None


@pytest.mark.parametrize("scenario", ("s2", "s3", "quiet"))
def test_e25_no_chain_for_nonpaging_disposition(world_case, scenario, monkeypatch):
    from argus.agent.board import build_board
    from argus.agent.chain import build_chain

    captured = []
    original = Runtime._investigate

    def investigate(runtime, *args, **kwargs):
        result = original(runtime, *args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(Runtime, "_investigate", investigate)
    runtime = stage2(world_case(scenario))
    assert not runtime.book.incidents
    assert all(finding.verdict in {Verdict.EXPECTED, Verdict.DATA_ISSUE} for finding in captured)
    assert all(build_board([], finding, None).chain is None for finding in captured)
    assert build_board([], None, None).chain is None
    if captured:
        (incident,) = stage2(world_case("s1")).book.incidents.values()
        verdict = captured[0].verdict
        negative = incident.model_copy(
            update={"findings": incident.findings.model_copy(update={"verdict": verdict, "root": None})}
        )
        assert build_chain(negative) is None


@pytest.mark.e2e
@pytest.mark.parametrize("scenario", CAUSES)
@pytest.mark.parametrize("seed", SEEDS)
def test_e25_chain_is_receipted_from_event_to_impact(world_case, scenario, seed):
    from argus.agent.chain import build_chain

    from argus.semantic.runner import Runner

    case = world_case(scenario, seed)
    runtime = stage2(case)
    (incident,) = runtime.book.incidents.values()
    assert incident.findings.root is not None
    cause, node, segment = CAUSES[scenario]
    assert incident.findings.root.segment == segment
    chain = build_chain(incident)
    assert chain is not None and chain.incident_id == incident.id
    assert chain.links[0].kind == "event" and chain.links[0].source == cause and chain.links[0].target == node
    assert any(link.kind == "root" and node in (link.source, link.target) for link in chain.links)
    impact = incident.findings.impact
    assert impact is not None
    (impact_link,) = [link for link in chain.links if link.kind == "impact"]
    assert impact_link.source == impact.node and impact_link.target == "eur"
    assert impact.eur_so_far.receipt in {link.receipt_id for link in impact_link.receipts}
    rerunner = Runner(case.world)
    try:
        rerunner.receipts.update(runtime.runner.receipts)
        for link in chain.links:
            assert link.receipts, link
            for proof in link.receipts:
                assert rerunner.rerun(proof.receipt_id)[1]
    finally:
        rerunner.close()
