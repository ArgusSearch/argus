"""The pre-verdict loop on the S1 seed-1 world with a scripted model: the model picks the checks, the
ledger judges them, the gate backfills what it skipped, and any failure completes as Stage 2 would."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from argus.agent.fake import FakeLlmClient
from argus.agent.investigate import AgentSelector, Budget
from argus.agent.journal import Journal
from argus.agent.provider import ProviderUnavailable
from argus.agent.types import LlmRequest, LlmResponse
from argus.contracts.findings import Anomaly, Findings, Verdict
from argus.contracts.graph import Graph
from argus.market.investigator import investigate
from argus.runtime.loop import Runtime
from argus.semantic.runner import Runner
from mockmart.world import WorldPaths

pytestmark = pytest.mark.e2e
Responder = Callable[[LlmRequest], LlmResponse]


@pytest.fixture(scope="module")
def case(s1_world: WorldPaths) -> tuple[Graph, Anomaly, datetime]:
    runtime = Runtime(s1_world.world)
    runtime.run()
    incident = next(iter(runtime.book.incidents.values()))
    anomaly = runtime.anomalies[incident.anomalies[0]]
    graph = runtime.graph
    runtime.runner.close()
    return graph, anomaly, incident.findings.as_of


def reply(*blocks: dict[str, Any]) -> LlmResponse:
    usage = {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return LlmResponse(model="claude-sonnet-5-5", content=list(blocks), stop_reason="tool_use", usage=usage)


def call(name: str, args: dict[str, Any], n: int, text: str = "") -> LlmResponse:
    blocks = [{"type": "text", "text": text}] if text else []
    return reply(*blocks, {"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": args})


def submit(n: int, verdict: str = "SUPPORTED_CAUSE") -> LlmResponse:
    return call("submit_findings", {"verdict": verdict, "summary": "done"}, n)


def packet(request: LlmRequest) -> dict[str, Any]:
    return json.loads(request.messages[0]["content"].split("<data>\n")[1].split("\n</data>")[0])  # type: ignore[no-any-return]


def last_result(request: LlmRequest) -> dict[str, Any]:
    return json.loads(request.messages[-1]["content"][0]["content"])  # type: ignore[no-any-return]


def scripted(
    test_refs: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    placebo: bool = True,
    expect: Callable[[dict[str, Any]], str] = lambda ev: "consistent",
    placebo_expect: str = "unusual",
) -> Responder:
    """list_events, then holdout_check for the events `test_refs` picks, then (optionally) the placebo."""
    state: dict[str, Any] = {"n": 0}

    def respond(request: LlmRequest) -> LlmResponse:
        state["n"] += 1
        n = state["n"]
        if n == 1:
            p = state["p"] = packet(request)
            ew = p["event_window"]
            args = {"start": ew["start"], "end": ew["end"], "covering": p["root_segment"]}
            return call("list_events", {**args, "hypothesis": "h", "prediction": "p", "expect": "found"}, n, "List.")
        if n == 2:
            state["queue"] = test_refs(last_result(request)["data"]["events"])
        p = state["p"]
        base = {"node": p["focus_node"], "segment": p["root_segment"], "window": p["window"]}
        if state["queue"]:
            ev = state["queue"].pop(0)
            meta = {"hypothesis": ev["description"], "prediction": "normal outside", "expect": expect(ev)}
            return call("holdout_check", {"event": ev, **base, **meta}, n, f"Test {ev['ref']}.")
        if placebo and not state.get("placebo"):
            state["placebo"] = True
            return call("placebo_test", {**base, "hypothesis": "h", "prediction": "p", "expect": placebo_expect}, n)
        return submit(n)

    return respond


def run(case: tuple[Graph, Anomaly, datetime], world: WorldPaths, client: Any, **kw: Any) -> tuple[Findings, Journal]:
    graph, anomaly, as_of = case
    journal = Journal()
    selector = AgentSelector(client, journal, mode="replay", **kw)
    runner = Runner(world.world)
    try:
        return investigate(graph, runner, anomaly, as_of, selector=selector), journal
    finally:
        runner.close()


def agent_steps(findings: Findings) -> list[str]:
    return [s.tool for s in findings.trail if "agent" in s.data]


def test_model_chosen_checks_decide_s1(case: Any, s1_world: WorldPaths) -> None:
    findings, journal = run(case, s1_world, FakeLlmClient(responder=scripted(lambda evs: evs)))
    assert findings.verdict is Verdict.SUPPORTED_CAUSE
    assert findings.root is not None and findings.root.evidence is not None
    assert findings.root.evidence.ref == "ps_payco_degraded"
    assert "dep_android-app_8.3.0" in {r.evidence.ref for r in findings.ruled_out if r.evidence}
    assert agent_steps(findings) == ["list_events", "holdout_check", "holdout_check", "holdout_check", "placebo_test"]
    assert findings.cost.llm_calls == 6
    kinds = [r.kind for r in journal.records]
    assert kinds.index("tool_call") < kinds.index("tool_result")  # prediction journaled before the result
    summary = next(iter(journal.runs.values()))
    assert summary.gate is not None and summary.gate.admitted == "SUPPORTED_CAUSE" and summary.status == "done"


def test_gate_backfills_skipped_checks(case: Any, s1_world: WorldPaths) -> None:
    only_release = scripted(lambda evs: [e for e in evs if e["ref"].startswith("dep_android")], placebo=False)
    findings, journal = run(case, s1_world, FakeLlmClient(responder=only_release))
    assert findings.verdict is Verdict.SUPPORTED_CAUSE  # PayCo was backfilled and validated by Stage 2's own check
    texts = [r.text for r in journal.records if r.kind == "gate"]
    assert any("untested candidate" in t for t in texts) and any("placebo_test" in t for t in texts)


def test_provider_failure_completes_as_stage_two(case: Any, s1_world: WorldPaths) -> None:
    def broken(_: LlmRequest) -> LlmResponse:
        raise ProviderUnavailable("timeout")

    findings, journal = run(case, s1_world, FakeLlmClient(responder=broken))
    assert findings.verdict is Verdict.SUPPORTED_CAUSE
    assert agent_steps(findings) == []
    summary = next(iter(journal.runs.values()))
    assert summary.status == "fallback" and summary.fallback and "timeout" in summary.fallback


def test_unlisted_event_is_rejected(case: Any, s1_world: WorldPaths) -> None:
    fake_event = {
        "log": "log_deploys",
        "ref": "dep_invented",
        "ts": "2026-11-21T17:00:00",
        "kind": "deploy",
        "description": "invented",
        "scope": {},
    }

    def respond(request: LlmRequest) -> LlmResponse:
        if len(request.messages) == 1:
            p = packet(request)
            args = {"event": fake_event, "node": p["focus_node"], "segment": p["root_segment"], "window": p["window"]}
            return call("holdout_check", {**args, "hypothesis": "h", "prediction": "p", "expect": "consistent"}, 1)
        assert last_result(request)["availability"] == "rejected"
        return submit(2)

    findings, _ = run(case, s1_world, FakeLlmClient(responder=respond))
    assert "dep_invented" not in json.dumps(findings.model_dump(mode="json"))


def test_budget_stops_a_looping_model(case: Any, s1_world: WorldPaths) -> None:
    def looping(request: LlmRequest) -> LlmResponse:
        p = packet(request)
        args = {"node": p["focus_node"], "segment": p["root_segment"], "window": p["window"]}
        return call("get_series", {**args, "hypothesis": "h", "prediction": "p"}, len(request.messages))

    findings, journal = run(case, s1_world, FakeLlmClient(responder=looping), budget=Budget(requests=3))
    assert findings.verdict is Verdict.SUPPORTED_CAUSE
    summary = next(iter(journal.runs.values()))
    assert summary.status == "budget" and summary.llm_calls == 3


def test_gate_reads_outcomes_not_the_models_framing(case: Any, s1_world: WorldPaths) -> None:
    """Lane D's E03 case: the model expects the release holdout to be refuted (ledger: validated)."""
    rival = scripted(
        lambda evs: evs,
        expect=lambda ev: "refuted" if ev["ref"].startswith("dep_") else "consistent",
        placebo_expect="recurring",
    )
    findings, _ = run(case, s1_world, FakeLlmClient(responder=rival))
    assert findings.verdict is Verdict.SUPPORTED_CAUSE
    assert findings.root is not None and findings.root.evidence is not None
    assert findings.root.evidence.ref == "ps_payco_degraded"
    ruled = {r.evidence.ref for r in findings.ruled_out if r.evidence}
    assert {"dep_android-app_8.3.0", "dep_checkout-service_1.2.6"} <= ruled
    assert not any("recur" in u for u in findings.uncertain)  # an unusual placebo stays unusual


def test_activity_carries_only_verified_numbers(case: Any, s1_world: WorldPaths) -> None:
    """Lane D's E07: a number the model makes up never reaches the activity log."""
    inner = scripted(lambda evs: evs)

    def boastful(request: LlmRequest) -> LlmResponse:
        response = inner(request)
        blocks = [{"type": "text", "text": "This costs EUR 987,654 and 42.42% of revenue."}, *response.content]
        return response.model_copy(update={"content": blocks})

    _, journal = run(case, s1_world, FakeLlmClient(responder=boastful))
    texts = " ".join(r.text for r in journal.records if r.actor == "model")
    assert "987,654" not in texts and "42.42" not in texts and "[unverified]" in texts
