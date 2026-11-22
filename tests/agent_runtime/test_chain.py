"""Cause chains (src/argus/agent/chain.py): event -> root node in its segment -> formula hop -> EUR, from findings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argus.agent.chain import STAGE2_RUN, build_chain
from argus.contracts.findings import Incident, Verdict

REPO = Path(__file__).resolve().parents[2]


def incident(path: str) -> Incident:
    [found] = [Incident.model_validate(raw) for raw in json.loads((REPO / path / "incidents.json").read_text())]
    return found


def test_s1_chain_reads_from_the_provider_outage_to_euros() -> None:
    inc = incident("fixtures/agent/v1/s1")
    chain = build_chain(inc, run_id="run_0001")
    assert chain is not None and chain.incident_id == "INC-0001"
    assert [link.kind for link in chain.links] == ["event", "root", "formula", "impact", "symptom", "symptom"]
    event, root, formula, impact = chain.links[:4]
    assert (event.source, event.target, event.status) == ("ps_payco_degraded", "payment_success_rate", "tested")
    assert [r.receipt_id for r in event.receipts] == ["r241"]  # the holdout that kept the cause
    assert root.label == "payment success rate in DE / android / PayCo" and root.share == 1.0
    assert (formula.source, formula.target, formula.share) == ("payment_success_rate", "orders", 1.0312)
    assert formula.label.endswith("[r246]")
    findings_impact = inc.findings.impact
    assert findings_impact is not None
    assert (impact.source, impact.target) == ("orders", "eur")
    assert impact.receipts[0].receipt_id == findings_impact.gmv_eur_per_hour.receipt
    assert "EUR -21,742 so far [r247]" in impact.label
    assert {link.target for link in chain.links if link.kind == "symptom"} == {"cvr", "gmv"}
    assert chain.text == (
        "PayCo: elevated decline rates for Android SDK payments in Germany -> payment success rate in "
        "DE / android / PayCo -> orders -> EUR -21,742 so far"
    )
    for link in chain.links:
        assert link.status == "untested" or link.receipts, link
        assert all(r.run_id == "run_0001" and r.world_revision == "factual" for r in link.receipts)


def test_s4_chain_names_the_pacer_deploy() -> None:
    chain = build_chain(incident("fixtures/agent/v1/s4"), run_id="run_0001")
    assert chain is not None
    assert chain.links[0].source == "dep_ad-pacer_1.7.0" and chain.links[0].target == "pacing_ratio"
    assert [(link.source, link.target) for link in chain.links if link.kind == "formula"] == [
        ("pacing_ratio", "ad_spend")
    ]
    assert chain.text.startswith("ad-pacer 1.7.0") and chain.text.endswith("EUR +1,768 so far")


@pytest.mark.parametrize("path", ["fixtures", "fixtures/s4", "fixtures/s5"])
def test_stage2_chains_cite_the_investigators_receipts(path: str) -> None:
    inc = incident(path)
    chain = build_chain(inc)
    assert chain is not None
    root = inc.findings.root
    assert root is not None and root.evidence is not None
    assert chain.links[0].source == root.evidence.ref and chain.links[1].target == root.node
    assert all(r.run_id == STAGE2_RUN for link in chain.links for r in link.receipts)
    assert all(link.receipts for link in chain.links if link.status == "tested")


@pytest.mark.parametrize("verdict", [Verdict.HYPOTHESIS, Verdict.EXPECTED, Verdict.UNEXPLAINED, Verdict.DATA_ISSUE])
def test_no_chain_without_a_supported_cause(verdict: Verdict) -> None:
    inc = incident("fixtures/agent/v1/s1")
    weaker = inc.model_copy(update={"findings": inc.findings.model_copy(update={"verdict": verdict})})
    assert build_chain(weaker) is None


def test_chain_is_deterministic() -> None:
    inc = incident("fixtures/agent/v1/s4")
    first = build_chain(inc)
    assert first is not None
    assert first.model_dump_json() == build_chain(inc.model_copy(deep=True)).model_dump_json()  # type: ignore[union-attr]
