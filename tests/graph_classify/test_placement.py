"""End to end on an S1 world: each demo metric lands where it belongs, with test results and a certificate."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from argus.contracts.graph import EdgeKind, EdgeStatus, Graph, Provenance
from argus.contracts.metric import MetricDefinition, load_metric
from argus.graph.classify import Candidate, Lifecycle, LlmProposer, Placement, classify, main
from argus.graph.edge_tests import EdgeTester
from argus.graph.store import Changelog
from argus.semantic.runner import Runner

METRICS = Path(__file__).parent / "metrics"


def metric(name: str) -> MetricDefinition:
    return load_metric(METRICS / f"{name}.yml")


def place(name: str, graph: Graph, runner: Runner, as_of: datetime, **kw: Any) -> Placement:
    return classify(metric(name), graph, runner, as_of, **kw)


def edge(p: Placement, describe: str) -> Candidate:
    return next(c for c in p.candidates if c.describe() == describe)


def test_new_ratio_lands_between_its_parents_and_children(seed: Graph, runner: Runner, as_of: datetime) -> None:
    changelog = Changelog()
    p = place("revenue_per_session", seed, runner, as_of, changelog=changelog)
    assert p.placed_as == "EXACT"
    node = p.graph.node("revenue_per_session")
    assert (node.kind, node.unit, node.numerator, node.denominator, node.state) == (
        "ratio",
        "eur_per_unit",
        "gmv",
        "sessions",
        "watching",
    )
    parent = edge(p, "gmv = sessions * revenue_per_session")
    child = edge(p, "revenue_per_session = cvr * aov")
    for cand in (parent, child):
        assert cand.lifecycle is Lifecycle.ACCEPTED and cand.edge.status is EdgeStatus.VALID
        assert cand.edge.provenance is Provenance.LINEAGE
        assert cand.result and cand.result.hours == 672 and (cand.result.median_rel or 0) < 1e-9
        assert cand.result.receipts and all(r in runner.receipts for r in cand.result.receipts)
    assert {c.edge.dim for c in p.candidates if c.edge.kind is EdgeKind.BREAKDOWN} == {"country", "platform"}
    kinds = [c.kind for c in changelog.entries]
    assert "node_added" in kinds and kinds.count("edge_added") == len(p.certificate.edges)
    assert p.certificate.receipts and p.certificate.passed
    assert len(seed.nodes) + 1 == len(p.graph.nodes)  # the input graph is untouched


def test_placed_edges_survive_the_standard_re_test(seed: Graph, runner: Runner, as_of: datetime) -> None:
    graph = seed
    for name in ("revenue_per_session", "click_conversion_rate", "orders_per_checkout", "roas_by_advertiser"):
        graph = place(name, graph, runner, as_of).graph
    Graph.model_validate(graph.model_dump())
    tester = EdgeTester(graph, runner)
    tester.run_all(as_of, Changelog())
    added = {e.id for e in graph.edges} - {e.id for e in seed.edges}
    for e in tester.graph.edges:
        if e.id in added and e.kind in (EdgeKind.FORMULA, EdgeKind.BREAKDOWN):
            assert e.status is EdgeStatus.VALID, e.id


def test_existing_ratio_factors_through_the_new_one(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = place("click_conversion_rate", seed, runner, as_of)
    assert p.placed_as == "EXACT" and p.node and p.node.unit == "share"
    assert edge(p, "cpc = click_conversion_rate * cpa").edge.status is EdgeStatus.VALID
    assert edge(p, "ad_conversions = ad_clicks * click_conversion_rate").edge.status is EdgeStatus.VALID


def test_arithmetic_search_finds_a_data_identity(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = place("orders_per_checkout", seed, runner, as_of)
    found = edge(p, "orders_per_checkout = attempt_rate * payment_success_rate")
    assert found.edge.provenance is Provenance.ARITHMETIC and found.edge.status is EdgeStatus.VALID
    assert "explains 100.0% of the variance" in found.verdict


def test_known_metric_with_new_breakdowns_is_a_new_dimension(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = place("roas_by_advertiser", seed, runner, as_of)
    assert (p.placed_as, p.alias_of, p.node) == ("NEW_DIMENSION", "roas", None)
    assert {e.id for e in p.added_edges()} == {"b_roas_advertiser_id", "b_roas_country"}
    assert all(e.status is EdgeStatus.VALID for e in p.added_edges())
    assert len(p.graph.nodes) == len(seed.nodes)
    assert any("names roas, and the definition agrees" in c for c in p.checks)


def test_scaled_copy_is_a_numeric_alias(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = place("cvr_percent", seed, runner, as_of)
    assert (p.placed_as, p.alias_of, p.alias_scale) == ("ALIAS", "cvr", 100.0)
    assert p.graph == seed


def test_filtered_metric_is_a_segment_of_an_existing_node(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = place("paid_sessions", seed, runner, as_of)
    assert (p.placed_as, p.alias_of, p.segment) == ("ALIAS", "sessions", {"channel": "paid"})


def test_fan_out_is_rejected_with_the_factor_and_a_repair(seed: Graph, runner: Runner, as_of: datetime) -> None:
    changelog = Changelog()
    p = place("payments_per_session", seed, runner, as_of, changelog=changelog)
    assert p.placed_as == "REJECTED" and p.graph == seed
    assert p.repair and p.repair.factor == pytest.approx(8.0, rel=1e-6)
    assert "8x" in p.certificate.summary and "join fan-out" in p.certificate.summary
    assert "+WITH num AS" in p.repair.diff and "-JOIN fact_funnel_hourly USING (ts, country, platform)" in p.repair.diff
    assert changelog.entries[-1].reason.startswith("REJECTED")


def test_derived_metric_is_verified_but_not_placed(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = place("payment_failures", seed, runner, as_of)
    assert p.placed_as == "REJECTED" and "derived node" in p.certificate.summary
    assert any(c.startswith("definition check: your SQL equals") for c in p.checks)


def test_tied_decompositions_make_the_placement_ambiguous(seed: Graph, runner: Runner, as_of: datetime) -> None:
    twin = seed.node("cvr").model_copy(update={"id": "cvr_twin", "north_star": False})
    graph = Graph(version=seed.version, nodes=[*seed.nodes, twin], edges=seed.edges, logs=seed.logs)
    p = place("revenue_per_session", graph, runner, as_of)
    assert p.placed_as == "AMBIGUOUS" and p.node and p.node.state == "probation"
    decomps = [c for c in p.candidates if c.edge.kind is EdgeKind.FORMULA and c.edge.target == "revenue_per_session"]
    assert sorted(c.lifecycle for c in decomps) == [Lifecycle.ACCEPTED, Lifecycle.TESTED]
    winner = next(c for c in decomps if c.lifecycle is Lifecycle.ACCEPTED)
    assert winner.edge.status is EdgeStatus.PROBATION and winner.edge.weight == 0.5
    assert any(u.startswith("ambiguous: 2 equally simple formulas fit") for u in p.certificate.uncertain)
    assert all(
        e.target != "revenue_per_session" or e.id == winner.edge.id
        for e in p.added_edges()
        if e.kind is EdgeKind.FORMULA
    )


def test_llm_proposes_and_the_math_decides(seed: Graph, runner: Runner, as_of: datetime) -> None:
    reply = {
        "edges": [
            {
                "kind": "formula",
                "target": "click_conversion_rate",
                "sources": ["ctr", "cpc"],
                "why": "wrong on purpose",
            },
            {"kind": "cause", "target": "click_conversion_rate", "sources": ["attributed_gmv"], "lag_hours": [0]},
            {"kind": "cause", "target": "click_conversion_rate", "sources": ["log_deploys"], "why": "releases"},
            {"kind": "cause", "target": "click_conversion_rate", "sources": ["nonexistent"]},
            {"kind": "formula", "target": "ad_conversions", "sources": ["ad_clicks", "click_conversion_rate"]},
        ]
    }
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return "```json\n" + json.dumps(reply) + "\n```"

    p = place("click_conversion_rate", seed, runner, as_of, proposers=[LlmProposer(complete)])
    assert "click_conversion_rate" in prompts[0] and "log_deploys" in prompts[0]
    wrong = edge(p, "click_conversion_rate = ctr * cpc")
    assert wrong.lifecycle is Lifecycle.REJECTED and wrong.verdict.startswith("failed")
    cause = edge(p, "attributed_gmv -> click_conversion_rate")
    assert cause.lifecycle is Lifecycle.ACCEPTED and cause.edge.status is EdgeStatus.SUPPORTED
    assert cause.edge.provenance is Provenance.LLM and cause.result and cause.result.passed
    evidence = edge(p, "log_deploys -> click_conversion_rate")
    assert evidence.lifecycle is Lifecycle.PROPOSED and evidence.edge.kind is EdgeKind.EVIDENCE
    assert evidence.edge in p.graph.edges and evidence.edge.weight == 0.0
    invalid = next(c for c in p.candidates if "unknown ids ['nonexistent']" in c.verdict)
    assert invalid.lifecycle is Lifecycle.REJECTED and invalid.edge not in p.graph.edges
    lineage_edge = edge(p, "ad_conversions = ad_clicks * click_conversion_rate")
    assert lineage_edge.proposed_by == "llm" and lineage_edge.edge.provenance is Provenance.LINEAGE
    assert not [
        c for c in p.candidates if c.edge.id.startswith("c_attributed_gmv") and c.edge.provenance is Provenance.LEARNED
    ]


def test_a_broken_proposer_never_breaks_placement(seed: Graph, runner: Runner, as_of: datetime) -> None:
    p = place("revenue_per_session", seed, runner, as_of, proposers=[LlmProposer(lambda _: "not json")])
    assert p.placed_as == "EXACT"
    assert any(u.startswith("proposer llm failed") for u in p.certificate.uncertain)


def test_cli_places_metrics_and_writes_the_graph(
    world: Path, as_of: datetime, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [str(METRICS / "revenue_per_session.yml"), str(METRICS / "payments_per_session.yml")]
    assert main([*args, "--world", str(world), "--as-of", as_of.isoformat(), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "revenue_per_session  ->  EXACT" in out and "payments_per_session  ->  REJECTED" in out
    assert "repair diff:" in out
    graph = Graph.model_validate_json((tmp_path / "graph.json").read_text())
    assert graph.node("revenue_per_session").kind == "ratio"
    certificates = json.loads((tmp_path / "certificates.json").read_text())
    assert [c["placed_as"] for c in certificates] == ["EXACT", "REJECTED"]
    assert (tmp_path / "graph_changelog.jsonl").read_text().count("\n") > 5
