"""S1 end to end with the Stage-2 investigator on several random seeds.

Each seed generates a fresh world (random onset, duration and size of the PayCo fault), runs the full
runtime over the live window with the Stage-2 investigator, and grades the result against the hidden
truth. Only this test reads truth.duckdb; Argus receives the world path and nothing else.

Seeds 1 and 4 also contain noise false alarms from the watcher (CPA, GMV); the investigator must label
them UNEXPLAINED instead of inventing a hypothesis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from argus.contracts.events import Event, EventType, InvestigationStepPayload
from argus.contracts.findings import Incident, Verdict
from argus.investigate import procedure
from argus.investigate.__main__ import run_world
from argus.investigate.claims import claims_of
from argus.investigate.ledger import Hypothesis
from argus.investigate.planner import ScriptedPlanner
from argus.investigate.procedure import StageTwoInvestigation
from argus.investigate.report import render_findings
from argus.narrator.report import unbacked_numbers
from argus.runtime.loop import Runtime
from mockmart.sim import WorldConfig
from mockmart.truth import read_truth
from mockmart.world import generate

pytestmark = pytest.mark.e2e
SEEDS = (1, 4, 7)


@dataclass
class Run:
    seed: int
    runtime: Runtime
    truth: dict[str, object]


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Run]:
    out = {}
    for seed in SEEDS:
        paths = generate("s1", WorldConfig(seed=seed), tmp_path_factory.mktemp(f"s1-{seed}"))
        runtime = run_world(paths.world)
        fault = next(e for e in read_truth(paths.truth) if e["kind"] == "fault")
        out[seed] = Run(seed, runtime, fault)
    return out


def payco_incident(run: Run) -> Incident:
    supported = [i for i in run.runtime.book.incidents.values() if i.verdict is Verdict.SUPPORTED_CAUSE]
    assert len(supported) == 1, [i.title for i in run.runtime.book.incidents.values()]
    return supported[0]


@pytest.mark.parametrize("seed", SEEDS)
def test_s1_reaches_payco_and_rules_out_the_release(runs: dict[int, Run], seed: int) -> None:
    run = runs[seed]
    expected = run.truth["expected"]
    assert isinstance(expected, dict)
    f = payco_incident(run).findings
    assert f.root is not None and f.root.evidence is not None
    assert f.root.node == expected["root_node"]
    assert f.root.segment == expected["segment"]
    assert f.root.evidence.ref == expected["evidence"]
    assert set(expected["ruled_out"]) <= {r.evidence.ref for r in f.ruled_out if r.evidence}
    assert f.explained_share >= 0.2


@pytest.mark.parametrize("seed", SEEDS)
def test_every_other_incident_is_labelled_unexplained(runs: dict[int, Run], seed: int) -> None:
    others = [i for i in runs[seed].runtime.book.incidents.values() if i.verdict is not Verdict.SUPPORTED_CAUSE]
    assert all(i.verdict is Verdict.UNEXPLAINED for i in others), [(i.verdict, i.title) for i in others]
    assert all(i.findings.explained_share == 0.0 and i.findings.root is None for i in others)


@pytest.mark.parametrize("seed", SEEDS)
def test_ledger_placebo_control_and_claim_labels(runs: dict[int, Run], seed: int) -> None:
    f = payco_incident(runs[seed]).findings
    verdict_step = f.trail[-1]
    ledger = verdict_step.data["ledger"]
    by_tool = {(e["hypothesis"]["tool"], e["status"]) for e in ledger}
    assert ("placebo_test", "validated") in by_tool
    assert ("holdout_check", "validated") in by_tool and ("holdout_check", "refuted") in by_tool
    # the PayCo notice covers exactly the root segment: the holdout is empty, so a control group decided
    cause = next(s for s in f.trail if s.tool == "holdout_check" and s.data["ledger"]["status"] == "validated")
    assert cause.data["output"]["holdout"]["kind"] == "control"
    assert cause.prediction and cause.hypothesis
    claims = claims_of(f)
    labels = {c.label for c in claims}
    assert labels == {"evidence", "hypothesis"}
    assert any(c.label == "evidence" and "ps_payco_degraded" in c.text for c in claims)
    assert all(c.receipts for c in claims if c.label == "evidence")


@pytest.mark.parametrize("seed", SEEDS)
def test_events_are_valid_c5_and_carry_the_stage_two_steps(runs: dict[int, Run], seed: int) -> None:
    events = runs[seed].runtime.bus.history
    for event in events:
        Event.model_validate(json.loads(event.model_dump_json()))
    steps = [
        InvestigationStepPayload.model_validate(e.payload).step
        for e in events
        if e.type is EventType.INVESTIGATION_STEP
    ]
    assert any(s.tool == "placebo_test" for s in steps)
    assert any(s.kind == "verdict" and "claims" in s.data for s in steps)
    # package #4: every step names its playbook step, the verdict carries the whole run
    assert all(s.data["playbook"]["label"] and s.data["playbook"]["name"].endswith("playbook") for s in steps)
    verdicts = [s for s in steps if s.kind == "verdict"]
    assert all({r["status"] for r in s.data["playbook_run"]} <= {"done", "skipped"} for s in verdicts)
    labels = [s.data["playbook"]["label"] for s in steps]
    assert "Placebo" in labels and "Hypothesis tests" in labels and "Exact split (LMDI)" in labels


@pytest.mark.parametrize("seed", SEEDS)
def test_report_passes_the_number_check_and_receipts_rerun(runs: dict[int, Run], seed: int) -> None:
    run = runs[seed]
    inc = payco_incident(run)
    report = render_findings(inc.findings, run.runtime.graph)
    assert "**EVIDENCE**" in report and "## Hypotheses tested" in report
    assert unbacked_numbers(report, inc.findings) == []
    receipts = {r for s in inc.findings.trail for r in s.receipts}
    for rid in sorted(receipts):
        _, same = run.runtime.runner.rerun(rid)
        assert same, rid


def test_planner_hypotheses_are_checked_by_the_ledger(runs: dict[int, Run], monkeypatch: pytest.MonkeyPatch) -> None:
    run = runs[SEEDS[-1]]
    inc = payco_incident(run)
    anomaly = run.runtime.anomalies[inc.anomalies[0]]
    root = inc.findings.root
    assert root is not None
    window = inc.findings.window.model_dump(mode="json")
    proposals = [
        Hypothesis(
            statement="the drop is a mix shift across platforms",
            prediction="every platform's own success rate is flat",
            tool="mix_rate_split",
            input={"node": "payment_success_rate", "dim": "platform", "window": window},
            expect="mix",
        ),
        Hypothesis(
            statement="the payment drop is confined to one segment",
            prediction="segment search localises it",
            tool="segment_search",
            input={"node": "payment_success_rate", "window": window},
            expect="localized",
        ),
    ]
    planner = ScriptedPlanner(proposals, name="replay")
    monkeypatch.setattr(procedure, "STOP_EXPLAINED", 1.01)  # force the planner phase
    findings = StageTwoInvestigation(
        run.runtime.graph, run.runtime.runner, anomaly, anomaly.detected_at, planner=planner
    ).run()
    assert planner.calls == 1
    planned = [e for e in findings.trail[-1].data["ledger"] if e["hypothesis"]["source"] == "planner:replay"]
    assert [(e["hypothesis"]["tool"], e["status"]) for e in planned] == [
        ("mix_rate_split", "refuted"),
        ("segment_search", "validated"),
    ]
    assert any(r.hypothesis.startswith("the drop is a mix shift") for r in findings.ruled_out)
    assert findings.verdict is Verdict.SUPPORTED_CAUSE


def test_cli_writes_stage_two_reports(tmp_path: Path) -> None:
    paths = generate("s1", WorldConfig(seed=2), tmp_path / "world")
    run_world(paths.world, tmp_path / "out")
    reports = sorted((tmp_path / "out" / "reports").glob("*.stage2.md"))
    assert reports and "Hypotheses tested" in reports[0].read_text()
