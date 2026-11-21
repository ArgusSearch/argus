"""Before/after cards and their C5 events, from onboarding and from a re-test that breaks an edge."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from argus.contracts.events import Event, EventType
from argus.contracts.graph import EdgeKind, EdgeStatus, Graph
from argus.contracts.metric import load_metric
from argus.graph.classify import classify, main
from argus.graph.classify_cards import placement_cards, retest_cards, to_events
from argus.graph.edge_tests import EdgeTester
from argus.graph.store import Changelog
from argus.semantic.runner import Runner

METRICS = Path(__file__).parent / "metrics"


def test_onboarding_cards_carry_the_test_value(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = classify(load_metric(METRICS / "revenue_per_session.yml"), seed, runner, as_of)
    cards = placement_cards(p)
    head, node, *edges = cards
    assert (head.subject_kind, head.before, head.after, head.tone) == ("metric", "new metric", "EXACT", "good")
    assert head.evidence == "your SQL = compiled gmv / sessions: residual 0.00 % over 672 h"
    assert (node.subject, node.before, node.after) == ("revenue_per_session", "absent", "watching")
    parent = next(c for c in edges if c.title == "gmv = sessions * revenue_per_session")
    assert (parent.before, parent.after, parent.tone) == ("PROPOSED", "VALID", "good")
    assert parent.evidence == "residual 0.00 %, p95 0.00 % over 672 h"
    assert parent.result and parent.receipts == parent.result.receipts
    assert len({c.id for c in cards}) == len(cards)


def test_fan_out_card_has_the_factor_and_the_repair_diff(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = classify(load_metric(METRICS / "payments_per_session.yml"), seed, runner, as_of)
    (card,) = placement_cards(p)
    assert (card.after, card.tone) == ("REJECTED", "bad")
    assert card.evidence.startswith("fan-out x8")
    assert card.diff and card.diff.startswith("--- payments_per_session.yml (as written)")


def test_alias_and_correlation_cards(seed: Graph, runner: Runner, as_of: datetime) -> None:
    alias = placement_cards(classify(load_metric(METRICS / "cvr_percent.yml"), seed, runner, as_of))
    assert [(c.after, c.evidence) for c in alias] == [("ALIAS", "same numbers as cvr x 100")]
    ccr = placement_cards(classify(load_metric(METRICS / "click_conversion_rate.yml"), seed, runner, as_of))
    cause = next(c for c in ccr if c.edge_kind is EdgeKind.CAUSE)
    assert (cause.after, cause.tone) == ("PROBATION", "watch")
    assert "BH q=" in cause.evidence and "correlated, not causal" in cause.detail


def test_a_re_test_that_breaks_an_edge_becomes_a_card(seed: Graph, runner: Runner, as_of: datetime) -> None:
    placed = classify(load_metric(METRICS / "revenue_per_session.yml"), seed, runner, as_of).graph
    tester = EdgeTester(placed, runner)
    assert retest_cards(tester.run_all(as_of, Changelog()), as_of) == []  # confirming a status is no news
    edges = [
        e.model_copy(update={"expr": "cvr * aov * 1.1"}) if e.id == "f_revenue_per_session_from_cvr_aov" else e
        for e in tester.graph.edges
    ]
    tester.graph = tester.graph.model_copy(update={"edges": edges})
    (card,) = retest_cards(tester.run_all(as_of, Changelog()), as_of)
    assert (card.subject, card.before, card.after, card.tone) == (
        "f_revenue_per_session_from_cvr_aov",
        "VALID",
        "BROKEN",
        "bad",
    )
    assert card.evidence.startswith("residual 10.00 %")


def test_cards_map_onto_c5_events(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = classify(load_metric(METRICS / "orders_per_checkout.yml"), seed, runner, as_of)
    events = [Event(seq=i, type=t, sim_ts=as_of, payload=payload) for i, (t, payload) in enumerate(to_events(p), 1)]
    status = [e for e in events if e.type is EventType.EDGE_STATUS]
    assert len(status) == len([c for c in p.candidates if c.enters_graph and c.result])
    assert all(e.payload["old_status"] is None for e in status)
    assert {e.payload["new_status"] for e in status} <= {s.value for s in EdgeStatus}
    assert sum(e.type is EventType.GRAPH_CHANGED for e in events) == len(p.changes)


def test_cli_writes_cards_and_events(
    world: Path, as_of: datetime, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [str(METRICS / "roas_by_advertiser.yml"), "--world", str(world), "--as-of", as_of.isoformat()]
    assert main([*args, "--cards", "--out", str(tmp_path)]) == 0
    assert "PROPOSED -> VALID         roas by advertiser_id" in capsys.readouterr().out
    cards = json.loads((tmp_path / "cards.json").read_text())
    assert [c["after"] for c in cards] == ["NEW_DIMENSION", "VALID", "VALID"]
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert [Event.model_validate_json(line).seq for line in lines] == list(range(1, len(lines) + 1))
