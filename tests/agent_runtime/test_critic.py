"""The counter-check (v2 `critic`): a second model tries to break a supported cause; fixed rules read its
checks and can only take the verdict away. Any failure leaves the deterministic verdict in the same tick."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytest

from argus.agent.fake import FakeLlmClient
from argus.agent.investigate import AgentSelector, Case
from argus.agent.journal import Journal
from argus.agent.profile import V1, Profile
from argus.agent.provider import OPENAI_SOL, ProviderUnavailable
from argus.agent.types import Challenge, LlmRequest, LlmResponse
from argus.contracts.findings import Anomaly, EvidenceRef, Findings, Verdict, Window
from argus.contracts.graph import Graph
from argus.market.investigator import investigate
from argus.runtime.loop import Runtime
from argus.semantic.runner import Runner
from argus.skeptic.critic import RULES, CriticBudget, CriticCheck, LlmCritic, counter_verdict
from mockmart.world import WorldPaths

CRITIC = Profile.of("v2", "critic")
ONSET = datetime(2026, 11, 21, 17)
SEGMENT = {"country": "DE", "platform": "android"}


def ev(ref: str, scope: dict[str, list[str]] | None = None, ts: datetime = ONSET) -> EvidenceRef:
    return EvidenceRef(log="log_deploys", ref=ref, ts=ts, kind="deploy", description=ref, scope=scope or {})


def fake_case() -> Case:
    anomaly = Anomaly(
        id="an_1",
        node="orders",
        segment={},
        hour=ONSET,
        detected_at=ONSET,
        direction="down",
        observed=1.0,
        expected=2.0,
        band=(1.5, 2.5),
        z=-5.0,
        rule="z_gt_open",
        onset=ONSET,
    )
    window = Window(start=ONSET - timedelta(hours=6), end=ONSET + timedelta(hours=2))
    return Case(anomaly, ONSET, "payment_success_rate", {}, SEGMENT, True, 0.9, -0.4, -6.0, ONSET, window)


def check(tool: str, outcome: str | None, event: EvidenceRef | None = None, **kw: Any) -> CriticCheck:
    base: dict[str, Any] = {"node": "payment_success_rate", "segment": SEGMENT, "summary": "s", "receipts": ["r1"]}
    return CriticCheck(call_id="run_0001:c1", tool=tool, event=event, outcome=outcome, **{**base, **kw})


# ---------------------------------------------------------------------------------------------- the rules


def test_rules_r1_to_r4_and_their_order() -> None:
    case, cause = fake_case(), ev("ps_payco", {"country": ["DE"], "provider": ["PayCo"]})
    rival = ev("dep_rival", {"country": ["DE"], "provider": ["PayCo"]}, ONSET - timedelta(hours=1))
    assert counter_verdict([], case, cause).verdict == "upheld"
    assert counter_verdict([check("holdout_check", "consistent", cause)], case, cause).rule is None
    r1 = counter_verdict([check("placebo_test", "recurring"), check("holdout_check", "refuted", cause)], case, cause)
    assert (r1.verdict, r1.rule) == ("refuted", "R1")  # R1 before R2, whatever the order of the checks
    r2 = counter_verdict([check("placebo_test", "recurring")], case, cause)
    assert (r2.verdict, r2.rule) == ("refuted", "R2")
    r3 = counter_verdict([check("holdout_check", "consistent", rival)], case, cause)
    assert (r3.verdict, r3.rule) == ("weakened", "R3") and "dep_rival" in r3.reason
    r4 = counter_verdict([check("sql_check", "fails", node=None, segment={})], case, cause)
    assert (r4.verdict, r4.rule) == ("weakened", "R4")


def test_rules_ignore_checks_off_the_case_and_weaker_rivals() -> None:
    case, cause = fake_case(), ev("ps_payco", {"country": ["DE"], "provider": ["PayCo"]})
    elsewhere = check("holdout_check", "refuted", cause, segment={"country": "FR"})
    other_node = check("placebo_test", "recurring", node="orders")
    rejected = check("placebo_test", "recurring", availability="rejected")
    broad = check("holdout_check", "consistent", ev("dep_broad", {"country": ["DE"]}))  # less specific
    late = check("holdout_check", "consistent", ev("dep_late", {"a": ["x"], "b": ["y"]}, ONSET + timedelta(hours=5)))
    assert counter_verdict([elsewhere, other_node, rejected, broad, late], case, cause).verdict == "upheld"


def test_rules_can_be_cut_one_by_one() -> None:
    case, cause = fake_case(), ev("ps_payco")
    rival = check("holdout_check", "consistent", ev("dep_rival", ts=ONSET - timedelta(minutes=1)))
    assert counter_verdict([rival], case, cause).rule == "R3"
    assert counter_verdict([rival], case, cause, frozenset(set(RULES) - {"R3"})).rule is None


def test_r3_requires_distinct_timing_and_a_contained_scope() -> None:
    case, cause = fake_case(), ev("dep_pacer", {"country": ["DE", "FR"]})
    earlier = ONSET - timedelta(minutes=5)
    scope = {"country": ["DE", "FR"], "advertiser_id": ["adv_a"]}
    same_change = ev("pacer_adv_a", scope, ts=ONSET)
    wider_change = ev("dep_wider", {"country": ["DE", "PL"], "advertiser_id": ["adv_a"]}, ts=earlier)
    for event in (same_change, wider_change):
        assert counter_verdict([check("holdout_check", "consistent", event)], case, cause).verdict == "upheld"
    independent = ev("dep_independent", scope, ts=earlier)
    assert counter_verdict([check("holdout_check", "consistent", independent)], case, cause).rule == "R3"


# ---------------------------------------------------------------------------------------------- on S1


@pytest.fixture(scope="module")
def case(s1_world: WorldPaths) -> tuple[Graph, Anomaly, datetime]:
    runtime = Runtime(s1_world.world)
    runtime.run()
    incident = next(iter(runtime.book.incidents.values()))
    anomaly = runtime.anomalies[incident.anomalies[0]]
    graph = runtime.graph
    runtime.runner.close()
    return graph, anomaly, incident.findings.as_of


USAGE = {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def reply(n: int, name: str, args: dict[str, Any], text: str = "", model: str = "claude-sonnet-5-5") -> LlmResponse:
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    blocks.append({"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": args})
    return LlmResponse(model=model, content=blocks, stop_reason="tool_use", usage=USAGE)


def data_block(request: LlmRequest, i: int = 0) -> Any:
    return json.loads(request.messages[0]["content"].split("<data>\n")[i + 1].split("\n</data>")[0])


def last_result(request: LlmRequest) -> dict[str, Any]:
    return json.loads(request.messages[-1]["content"][0]["content"])  # type: ignore[no-any-return]


SECRET = "My private hunch: the android release is a decoy."


def detective(request: LlmRequest) -> LlmResponse:
    """v1-style detective: one visible thought, then submit (the gate backfills Stage 2's checks)."""
    return LlmResponse(
        model="claude-sonnet-5-5",
        content=[
            {"type": "text", "text": SECRET},
            {
                "type": "tool_use",
                "id": "toolu_d",
                "name": "submit_findings",
                "input": {"verdict": "SUPPORTED_CAUSE", "summary": SECRET},
            },
        ],
        stop_reason="tool_use",
        usage=USAGE,
    )


def critic_script(plan: str) -> Any:
    """'falsify': holdout of the claimed cause and a placebo, then submit; 'rivals': holdout of every
    candidate; 'loop': never stops calling tools."""
    state: dict[str, Any] = {"n": 0, "queue": None}

    def respond(request: LlmRequest) -> LlmResponse:
        state["n"] += 1
        n = state["n"]
        p = data_block(request, 0)
        base = {"node": p["focus_node"], "segment": p["root_segment"], "window": p["window"]}
        meta = {"hypothesis": "the cause is wrong", "prediction": "it moves outside too"}
        if state["queue"] is None:
            if plan == "falsify":
                state["queue"] = [("holdout_check", {"event": p["claimed_cause"]}), ("placebo_test", {})]
            elif plan == "rivals":
                state["queue"] = [("holdout_check", {"event": e}) for e in p["candidates"]]
            else:
                state["queue"] = [("get_series", {})] * 10
        if state["queue"]:
            name, extra = state["queue"].pop(0)
            return reply(n, name, {**extra, **base, **meta}, "If it is wrong, this shows it.", "claude-opus-5-5")
        return reply(n, "submit_challenge", {"opinion": "upheld", "summary": "it held"}, model="claude-opus-5-5")

    return respond


def routed(critic: Any) -> FakeLlmClient:
    return FakeLlmClient(responder=lambda r: critic(r) if r.key.startswith("critic:") else detective(r))


def run(
    case: tuple[Graph, Anomaly, datetime], world: WorldPaths, client: Any, profile: Profile = CRITIC, **kw: Any
) -> tuple[Findings, Journal]:
    graph, anomaly, as_of = case
    journal = Journal()
    selector = AgentSelector(client, journal, mode="replay", profile=profile, **kw)
    runner = Runner(world.world)
    try:
        return investigate(graph, runner, anomaly, as_of, selector=selector), journal
    finally:
        runner.close()


def critic_line(journal: Journal) -> dict[str, Any]:
    lines = [r for r in journal.records if r.kind == "critic"]
    assert len(lines) == 1 and lines[0].role == "skeptic"
    return lines[0].args or {}


@pytest.mark.e2e
def test_openai_sol_critic_has_a_fresh_context(case: Any, s1_world: WorldPaths) -> None:
    def respond(request: LlmRequest) -> LlmResponse:
        assert request.model == OPENAI_SOL
        if request.key.startswith("critic:"):
            assert len(request.messages) == 1
            assert SECRET not in request.messages[0]["content"]
            return reply(1, "submit_challenge", {"opinion": "upheld", "summary": "it held"}, model=OPENAI_SOL)
        return detective(request).model_copy(update={"model": OPENAI_SOL})

    findings, journal = run(
        case, s1_world, FakeLlmClient(responder=respond), model=OPENAI_SOL, critic_model=OPENAI_SOL
    )
    assert findings.verdict == "SUPPORTED_CAUSE"
    assert critic_line(journal)["verdict"] == "upheld"


@pytest.mark.e2e
def test_a_true_cause_survives_the_counter_check(case: Any, s1_world: WorldPaths) -> None:
    client = routed(critic_script("falsify"))
    findings, journal = run(case, s1_world, client)
    assert findings.verdict is Verdict.SUPPORTED_CAUSE
    assert findings.root is not None and findings.root.evidence is not None
    assert findings.root.evidence.ref == "ps_payco_degraded"
    assert findings.skeptic is not None and findings.skeptic.verdict == "upheld"
    assert [c["tool"] for c in findings.skeptic.checks] == ["holdout_check", "placebo_test"]
    line = critic_line(journal)
    assert Challenge.model_validate({k: v for k, v in line.items() if k != "model"}).verdict == "upheld"
    assert line["model"] == "claude-opus-5-5"

    critic_requests = [r for r in client.requests if r.key.startswith("critic:")]
    assert [r.key for r in critic_requests] == [f"critic:{case[1].id}:{i}" for i in (1, 2, 3)]
    for request in critic_requests:  # fresh context: the detective's thoughts never reach the critic
        assert request.model == "claude-opus-5-5" != "claude-sonnet-5-5"
        assert SECRET not in json.dumps(request.model_dump())
        assert {t["name"] for t in request.tools} >= {"holdout_check", "placebo_test", "submit_challenge"}
        assert "submit_findings" not in {t["name"] for t in request.tools}

    calls = [r for r in journal.records if r.kind == "tool_call" and r.role == "skeptic" and r.actor == "model"]
    results = [r for r in journal.records if r.kind == "tool_result" and r.role == "skeptic"]
    assert len(calls) == 2 and [r.observation.call_id for r in results if r.observation] == [
        "run_0001:c1",
        "run_0001:c2",
    ]
    critic_steps = [s for s in findings.trail if s.data.get("agent", {}).get("role") == "critic"]
    assert [s.tool for s in critic_steps] == ["holdout_check", "placebo_test"]
    assert findings.trail[-1].kind == "verdict" and critic_steps[-1].step < findings.trail[-1].step
    summary = journal.runs["run_0001"]
    assert summary.llm_calls == 4 and findings.cost.llm_calls == 4  # one detective call, three critic calls
    assert summary.gate is not None and summary.gate.admitted == "SUPPORTED_CAUSE"


@pytest.mark.e2e
def test_testing_every_rival_vetoes_nothing_on_s1(case: Any, s1_world: WorldPaths) -> None:
    findings, _ = run(case, s1_world, routed(critic_script("rivals")))
    assert findings.verdict is Verdict.SUPPORTED_CAUSE
    assert findings.skeptic is not None and findings.skeptic.verdict == "upheld"
    tested = {c["event_ref"] for c in findings.skeptic.checks}
    assert "dep_android-app_8.3.0" in tested and "ps_payco_degraded" in tested


@pytest.mark.e2e
def test_a_failing_critic_leaves_the_verdict_in_the_same_tick(case: Any, s1_world: WorldPaths) -> None:
    def broken(request: LlmRequest) -> LlmResponse:
        raise ProviderUnavailable("cassette miss")

    findings, journal = run(case, s1_world, routed(broken))
    baseline, _ = run(case, s1_world, routed(broken), profile=V1)
    assert findings.verdict is baseline.verdict is Verdict.SUPPORTED_CAUSE
    assert findings.root == baseline.root and findings.skeptic is None
    assert critic_line(journal)["verdict"] == "unavailable"
    assert not [r for r in journal.records if r.kind == "critic" and "cassette miss" not in r.text]


@pytest.mark.e2e
def test_critic_skips_a_model_shared_with_the_detective(case: Any, s1_world: WorldPaths) -> None:
    client = routed(critic_script("falsify"))
    findings, journal = run(case, s1_world, client, model="claude-opus-5-5")
    assert findings.verdict is Verdict.SUPPORTED_CAUSE and findings.skeptic is None
    assert not any(request.key.startswith("critic:") for request in client.requests)
    assert "different model" in critic_line(journal)["reason"]


@pytest.mark.e2e
def test_a_looping_critic_stops_at_its_caps(case: Any, s1_world: WorldPaths) -> None:
    budget = CriticBudget(requests=10, tool_calls=3, usd=0.20, wall_seconds=45)
    graph, anomaly, as_of = case
    journal = Journal()
    client = routed(critic_script("loop"))
    selector = AgentSelector(client, journal, mode="replay", profile=CRITIC)
    selector.critic = LlmCritic(client, journal, profile=CRITIC, budget=budget)
    runner = Runner(s1_world.world)
    try:
        findings = investigate(graph, runner, anomaly, as_of, selector=selector)
    finally:
        runner.close()
    assert findings.verdict is Verdict.SUPPORTED_CAUSE and findings.skeptic is not None
    assert len([r for r in journal.records if r.kind == "tool_result" and r.role == "skeptic"]) == 3
    critic_usage = [u for u in journal.usage if u.model == "claude-opus-5-5"]
    assert len(critic_usage) == 3 and sum(u.usd or 0 for u in critic_usage) <= budget.usd


class Vetoing:
    """A selector whose challenge always downgrades: the verdict drops, nothing else is granted."""

    def __init__(self, inner: AgentSelector, verdict: str = "refuted") -> None:
        self.inner, self.verdict, self.asked = inner, verdict, 0

    def select(self, inv: Any, case: Any) -> Any:
        return self.inner.select(inv, case)

    def close(self, inv: Any, selection: Any, admitted: str) -> None:
        self.inner.close(inv, selection, admitted)

    def challenge(self, inv: Any, case: Any, selection: Any, supported: EvidenceRef) -> Challenge:
        self.asked += 1
        return Challenge(verdict=self.verdict, downgrade=True, reason=f"R1: {supported.ref} moves outside", checks=[])


@pytest.mark.e2e
def test_a_downgrade_removes_the_cause_and_its_action(case: Any, s1_world: WorldPaths) -> None:
    graph, anomaly, as_of = case
    vetoing = Vetoing(AgentSelector(routed(critic_script("falsify")), Journal(), mode="replay"))
    runner = Runner(s1_world.world)
    try:
        findings = investigate(graph, runner, anomaly, as_of, selector=vetoing)
    finally:
        runner.close()
    assert vetoing.asked == 1
    assert findings.verdict is Verdict.HYPOTHESIS
    assert findings.root is not None and findings.root.evidence is None
    assert findings.skeptic is not None and findings.skeptic.verdict == "refuted"
    assert any(u.startswith("Counter-check refuted the supported cause") for u in findings.uncertain)
    verdict_step = findings.trail[-1]
    assert verdict_step.result == "HYPOTHESIS" and "counter-check refuted" in (verdict_step.why or "")
    assert findings.suggested_action is None or "Roll back" not in findings.suggested_action.text


@pytest.mark.e2e
def test_v1_never_asks_for_a_challenge(case: Any, s1_world: WorldPaths) -> None:
    findings, journal = run(case, s1_world, routed(critic_script("falsify")), profile=V1)
    assert findings.skeptic is None
    assert not [r for r in journal.records if r.kind == "critic" or (r.role == "skeptic" and r.actor == "model")]
