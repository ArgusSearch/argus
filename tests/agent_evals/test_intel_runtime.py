"""Drive the real v2 selector, investigator and critic with recorded-shape model responses."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from scripts.agent_eval.bench_gate import SCENARIOS
from scripts.agent_eval.bench_gate import SEEDS as BENCH_SEEDS
from test_intel_board import SEEDS, stage2
from test_intel_sql import PREDICT, comparison_sql
from test_intel_sql import payments as payments
from test_runtime_gates import (
    CHECKS,
    call,
    scripted,
    series_args,
    submit,
)
from test_runtime_gates import (
    world_case as world_case,
)

from argus.agent.fake import FakeLlmClient, tool_use
from argus.agent.investigate import AgentSelector
from argus.agent.journal import Journal
from argus.agent.provider import ProviderUnavailable, SpendLedger
from argus.contracts.findings import Verdict
from argus.runtime.loop import Runtime

DECOY = "dep_android-app_8.3.0"
REAL_CAUSE = "ps_payco_degraded"
THOUGHT = "The detective keeps this private thought out of the independent context."


def run_v2(case, responder, *, features=(), mode="replay", spend=None, first_incident=False):
    from argus.agent.profile import Profile

    profile = Profile(name="v2", features=frozenset(features))
    client = FakeLlmClient(responder=responder)
    journal = Journal()
    runtime: Runtime
    selector = AgentSelector(
        client,
        journal,
        profile=profile,
        mode=mode,
        spend=spend,
        through_seq=lambda: runtime.bus.history[-1].seq,
    )
    runtime = Runtime(case.world, selector=selector)
    try:
        for tick in runtime.ticks():
            runtime.tick(tick)
            if first_incident and runtime.book.incidents:
                break
        assert not runtime.fallbacks
    finally:
        runtime.runner.close()
    return runtime, journal, client.requests


def critic_call(request, name, args):
    return tool_use(name, args, model=request.model, n=int(request.key.rsplit(":", 1)[1]))


def critic_results(journal):
    return [
        entry.observation
        for entry in journal.records
        if entry.kind == "tool_result"
        and entry.observation is not None
        and entry.observation.call_id.rsplit(":", 1)[-1].startswith("c")
    ]


def end_critic(request):
    return critic_call(request, "submit_challenge", {"opinion": "upheld", "summary": "The check is complete."})


def nonrefuting(request):
    if not request.key.startswith("critic:"):
        return scripted(request)
    if request.key.endswith(":1"):
        return critic_call(request, "placebo_test", {**series_args(request), **CHECKS, "expect": "recurring"})
    return end_critic(request)


@pytest.mark.parametrize("remove_cause", (False, True), ids=("supported", "no-cause"))
def test_e20_sql_only_cannot_grant_and_backfills(payments, world_case, tmp_path, remove_cause):
    case = world_case("s1")
    _, findings = payments
    if remove_cause:
        case = copy_world(case, tmp_path / "without-cause")
        with duckdb.connect(str(case.world)) as conn:
            conn.execute("DELETE FROM raw_provider_status WHERE id = ?", [REAL_CAUSE])
        (baseline,) = stage2(case, first_incident=True).book.incidents.values()
        findings = baseline.findings
        assert findings.verdict == Verdict.HYPOTHESIS
    sql = comparison_sql(findings.window.start, findings.window.end)

    def checks_only(request):
        if request.key.endswith(":1"):
            return call(
                request,
                "sql_check",
                {
                    "sql": sql,
                    "hypothesis": "The outage was isolated to PayCo.",
                    "prediction": "PayCo has a lower success rate.",
                    "predict": PREDICT,
                },
            )
        return submit(request)

    runtime, journal, _ = run_v2(case, checks_only, features=("sql",), first_incident=True)
    (incident,) = runtime.book.incidents.values()
    assert incident.verdict == findings.verdict
    (result,) = [
        r.observation
        for r in journal.records
        if r.kind == "tool_result" and r.tool == "sql_check" and r.observation is not None
    ]
    assert result.availability == "ok" and result.outcome == "holds" and result.receipt_refs
    (summary,) = journal.runs.values()
    assert summary.gate and summary.gate.admitted == findings.verdict
    assert all(any(tool in reason for reason in summary.gate.reasons) for tool in ("holdout_check", "placebo_test"))
    assert {"holdout_check", "placebo_test"} <= {step.tool for step in incident.findings.trail}


def copy_world(case, directory):
    directory.mkdir()
    database = directory / case.world.name
    manifest = directory / case.manifest.name
    shutil.copyfile(case.world, database)
    shutil.copyfile(case.manifest, manifest)
    return replace(case, world=database, manifest=manifest)


def decoy_world(case, destination):
    decoy = copy_world(case, destination / "decoy")
    with duckdb.connect(str(decoy.world)) as conn:
        ts, scope = conn.execute("SELECT ts, scope FROM raw_provider_status WHERE id = ?", [REAL_CAUSE]).fetchone()
        closer = ts.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        conn.execute(
            "UPDATE raw_deploys SET ts = ?, scope = ?, description = ? WHERE id = ?",
            [closer, scope, "An Android SDK rollout in the affected payment segment", DECOY],
        )
    return decoy


@pytest.mark.e2e
@pytest.mark.parametrize("seed", SEEDS)
def test_e21_planted_false_cause_is_downgraded(world_case, tmp_path: Path, seed):
    case = decoy_world(world_case("s1", seed), tmp_path)
    (baseline,) = stage2(case, first_incident=True).book.incidents.values()
    assert baseline.verdict == Verdict.SUPPORTED_CAUSE
    assert baseline.findings.root.evidence.ref == DECOY, "the planted cause must first fool Stage 2"
    findings = baseline.findings

    def check_rival(request):
        if not request.key.startswith("critic:"):
            return scripted(request)
        if not request.key.endswith(":1"):
            return end_critic(request)
        args = {
            "node": findings.root.node,
            "segment": findings.root.segment,
            "window": findings.window.model_dump(mode="json"),
            **CHECKS,
            "expect": "refuted",
            "event": {"log": "log_provider_status", "ref": REAL_CAUSE},
        }
        return critic_call(request, "holdout_check", args)

    runtime, _, _ = run_v2(case, check_rival, features=("critic",), first_incident=True)
    (incident,) = runtime.book.incidents.values()
    assert incident.verdict != Verdict.SUPPORTED_CAUSE
    skeptic = incident.findings.skeptic
    assert skeptic is not None and skeptic.verdict in {"weakened", "refuted"} and skeptic.checks


@pytest.mark.e2e
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("scenario", ("s1", "s4"))
def test_e21_true_cause_has_no_false_veto(world_case, scenario, seed):
    runtime, _, _ = run_v2(world_case(scenario, seed), nonrefuting, features=("critic",), first_incident=True)
    (incident,) = runtime.book.incidents.values()
    assert incident.verdict == Verdict.SUPPORTED_CAUSE
    skeptic = incident.findings.skeptic
    assert skeptic is not None and skeptic.verdict == "upheld"
    assert any(check["outcome"] == "unusual" and check["receipts"] for check in skeptic.checks)


def disposition(runtime):
    return {
        incident.findings.anomaly_id: (incident.verdict, incident.findings.as_of)
        for incident in runtime.book.incidents.values()
    }


@pytest.mark.e2e
@pytest.mark.parametrize("seed", BENCH_SEEDS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_e22_all_bench_cases_are_monotone(world_case, scenario, seed):
    case = world_case(scenario, seed)
    baseline = stage2(case)
    runtime, _, requests = run_v2(case, nonrefuting, features=("critic",))
    before = disposition(baseline)
    after = disposition(runtime)
    assert after.keys() == before.keys()
    for anomaly, (actual, clock) in after.items():
        expected, expected_clock = before[anomaly]
        assert clock == expected_clock
        assert actual == expected or (
            expected == Verdict.SUPPORTED_CAUSE and actual in {Verdict.HYPOTHESIS, Verdict.UNEXPLAINED}
        )

    # Stage 2 publishes EXPECTED and DATA_ISSUE as notes rather than incidents.
    def early_notes(rt):
        return [
            (note.kind, note.sim_ts, note.node, note.segment, note.reason)
            for note in rt.book.notes
            if note.kind in {"expected", "data_issue"}
        ]

    assert early_notes(runtime) == early_notes(baseline)
    assert bool([r for r in requests if r.key.startswith("critic:")]) == any(
        verdict == Verdict.SUPPORTED_CAUSE for verdict, _ in before.values()
    )


@pytest.mark.parametrize("fail", (False, True), ids=("loop", "unavailable"))
def test_e22_critic_is_isolated_and_bounded(world_case, payments, fail):
    case = world_case("s1")
    _, deterministic = payments

    def respond(request):
        if not request.key.startswith("critic:"):
            response = scripted(request)
            return response.model_copy(update={"content": [{"type": "text", "text": THOUGHT}, *response.content]})
        if fail:
            raise ProviderUnavailable("scripted critic unavailable")
        return critic_call(request, "placebo_test", {**series_args(request), **CHECKS, "expect": "recurring"})

    runtime, journal, requests = run_v2(case, respond, features=("critic",), first_incident=True)
    (incident,) = runtime.book.incidents.values()
    critics = [r for r in requests if r.key.startswith("critic:")]
    detective = [r for r in requests if r.key.startswith("investigate:")]
    assert any(THOUGHT in json.dumps(request.messages) for request in detective)
    detective_models = {r.model for r in detective}
    assert 1 <= len(critics) <= 3
    assert detective_models.isdisjoint(r.model for r in critics)
    assert all(THOUGHT not in r.system and THOUGHT not in json.dumps(r.messages) for r in critics)
    calls = critic_results(journal)
    assert len(calls) <= 3
    if not fail:
        assert calls and any(item.receipt_refs for item in calls)
    assert sum(u.usd or 0 for u in journal.usage if u.model in {r.model for r in critics}) <= 0.20
    assert incident.verdict == deterministic.verdict and incident.findings.as_of == deterministic.as_of
    if fail:
        unavailable = [r for r in journal.records if r.kind == "critic" and "unavailable" in r.text.lower()]
        assert len(unavailable) == 1 and unavailable[0].sim_ts == deterministic.as_of


def test_e26_detective_and_critic_budget_caps(world_case, tmp_path):
    def loop(request):
        if request.key.startswith("critic:"):
            return critic_call(request, "placebo_test", {**series_args(request), **CHECKS, "expect": "recurring"})
        return call(request, "get_series", series_args(request))

    path = tmp_path / "spend.jsonl"
    runtime, journal, requests = run_v2(
        world_case("s1"),
        loop,
        features=("critic",),
        mode="record",
        spend=SpendLedger(path),
        first_incident=True,
    )
    (incident,) = runtime.book.incidents.values()
    (run,) = journal.runs.values()
    assert run.status == "budget" and incident.verdict == Verdict.SUPPORTED_CAUSE
    detective_calls = [r.observation for r in journal.records if r.kind == "tool_result" and r.tool == "get_series"]
    assert 0 < len(detective_calls) <= 12
    critics = {r.model for r in requests if r.key.startswith("critic:")}
    assert critics
    critic_calls = critic_results(journal)
    assert 0 < len(critic_calls) <= 3
    assert run.tool_calls == len(detective_calls) + len(critic_calls)
    assert 0 < sum(u.usd or 0 for u in journal.usage if u.model in critics) <= 0.20
    assert 0 < sum(u.usd or 0 for u in journal.usage if u.model not in critics) <= 0.50
    assert path.read_bytes()


def test_e26_replay_reports_exact_cost_without_spend(world_case, tmp_path):
    from argus.agent.board import build_board

    replay_path = tmp_path / "replay-spend.jsonl"
    replay, replay_journal, _ = run_v2(
        world_case("s1"),
        nonrefuting,
        features=("critic",),
        spend=SpendLedger(replay_path),
        first_incident=True,
    )
    (replayed,) = replay.book.incidents.values()
    (summary,) = replay_journal.runs.values()
    assert summary.status == "done"
    board = build_board(replay_journal.records, replayed.findings, summary)
    billed = sum(Decimal(str(u.usd)) for u in replay_journal.usage if u.usd is not None)
    assert Decimal(str(board.cost.usd)) == billed > 0
    assert board.cost.replayed
    assert not replay_path.exists() or replay_path.read_bytes() == b""
