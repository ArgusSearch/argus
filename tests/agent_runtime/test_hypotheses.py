"""Declared hypotheses (v2): the host's book moves cards only on judged checks, and the loop that declares
them still ends with the deterministic verdict."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest

from argus.agent.fake import FakeLlmClient
from argus.agent.hypotheses import Declined, HypothesisBook, parse
from argus.agent.investigate import AgentSelector
from argus.agent.journal import Journal
from argus.agent.profile import Profile
from argus.agent.types import DeclaredHypothesis, HypothesisMove, LlmRequest, LlmResponse
from argus.contracts.findings import Anomaly, EvidenceRef, Findings, RuledOut, Verdict
from argus.contracts.graph import Graph
from argus.market.investigator import investigate
from argus.runtime.loop import Runtime
from argus.semantic.runner import Runner
from mockmart.world import WorldPaths

HYPOTHESES = Profile.of("v2", "hypotheses")


def card(id: str, kind: str = "event", **extra: Any) -> dict[str, Any]:
    return {
        "id": id,
        "statement": f"the {kind} explains it",
        "kind": kind,
        "decisive_check": "holdout_check" if kind == "event" else "placebo_test",
        "why_cheapest": "one query decides it",
        **extra,
    }


def event(ref: str) -> EvidenceRef:
    return EvidenceRef(log="log_deploys", ref=ref, ts=datetime(2026, 11, 21, 17), kind="deploy", description=ref)


# ---------------------------------------------------------------------------------------------- the book


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ({"hypotheses": [card("H1")]}, "2 to 5"),
        ({"hypotheses": [card(f"H{i}") for i in range(1, 7)]}, "2 to 5"),
        ({"hypotheses": [card("H1"), card("H1")]}, "unique"),
        ({"hypotheses": [card("H1"), card("A2")]}, "'H1' to 'H5'"),
        ({"hypotheses": [card("H1"), card("H2", statement="release 8.3.0 broke it")]}, "without digits"),
        ({"hypotheses": [card("H1"), card("H2", decisive_check="read_minds")]}, "decisive_check must be"),
        ({"hypotheses": [card("H1"), card("H2", parent="H9")]}, "not another"),
        ({"hypotheses": [card("H1"), card("H2", parent="H1"), card("H3", parent="H2")]}, "two levels"),
        ({"hypotheses": [card("H1"), card("H2", kind="astrology")]}, "invalid"),
    ],
)
def test_declarations_the_host_refuses(raw: dict[str, Any], why: str) -> None:
    with pytest.raises(Declined, match=why):
        parse(raw)


def test_cards_move_only_on_decisive_judged_checks() -> None:
    book = HypothesisBook()
    cards = book.declare(
        {"hypotheses": [card("H1", event_ref="ps_payco"), card("H2"), card("H3", kind="recurring"), card("H4", "mix")]}
    )
    assert [c.id for c in cards] == ["H1", "H2", "H3", "H4"]
    with pytest.raises(Declined, match="already declared"):
        book.declare({"hypotheses": [card("H1"), card("H2")]})
    h1, h2, h3 = book.cards["H1"], book.cards["H2"], book.cards["H3"]
    # a tool that cannot decide the kind attaches without moving
    assert book.observe(h1, "r:1", "get_series", None, on_case=True) is None and h1.status == "open"
    # a check off the case never moves a card
    assert book.observe(h1, "r:2", "holdout_check", "consistent", on_case=False, event_ref="ps_payco") is None
    # a holdout of a different event than the card names does not move it
    assert book.observe(h1, "r:3", "holdout_check", "refuted", on_case=True, event_ref="dep_other") is None
    move = book.observe(h1, "r:4", "holdout_check", "consistent", on_case=True, event_ref="ps_payco")
    assert move == HypothesisMove(id="H1", status="supported", reason=move.reason, call_id="r:4")
    # an event card without a ref binds to the first event it is tested on
    book.observe(h2, "r:5", "holdout_check", "refuted", on_case=True, event_ref="dep_android")
    assert h2.status == "ruled_out" and h2.declared.event_ref == "dep_android"
    book.observe(h3, "r:6", "placebo_test", None, on_case=True)
    assert h3.status == "inconclusive"
    # a self-written check can rule out, never support
    assert book.observe_sql(book.cards["H4"], "r:7", "holds", "rows agree") is None
    assert book.cards["H4"].status == "open"
    assert book.decisive_first() == pytest.approx(2 / 4)
    moves = book.settle([], [], placebo_outcome="unusual")
    assert [(m.id, m.status) for m in moves] == [("H3", "ruled_out"), ("H4", "not_tested")]
    assert not book.open_cards()


def test_settle_follows_what_the_gate_admitted() -> None:
    book = HypothesisBook()
    book.declare({"hypotheses": [card("H1", event_ref="ps_payco"), card("H2", event_ref="dep_android")]})
    ruled = RuledOut(hypothesis="d", prediction="p", result="refuted", reason="r", evidence=event("dep_android"))
    moves = book.settle([event("ps_payco")], [ruled], placebo_outcome=None)
    assert {m.id: m.status for m in moves} == {"H1": "supported", "H2": "ruled_out"}


# ---------------------------------------------------------------------------------------------- the loop on S1


@pytest.fixture(scope="module")
def case(s1_world: WorldPaths) -> tuple[Graph, Anomaly, datetime]:
    runtime = Runtime(s1_world.world)
    runtime.run()
    incident = next(iter(runtime.book.incidents.values()))
    anomaly = runtime.anomalies[incident.anomalies[0]]
    graph = runtime.graph
    runtime.runner.close()
    return graph, anomaly, incident.findings.as_of


def reply(n: int, name: str, args: dict[str, Any], text: str = "") -> LlmResponse:
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    blocks.append({"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": args})
    usage = {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return LlmResponse(model="claude-sonnet-5-5", content=blocks, stop_reason="tool_use", usage=usage)


def packet(request: LlmRequest) -> dict[str, Any]:
    return json.loads(request.messages[0]["content"].split("<data>\n")[1].split("\n</data>")[0])  # type: ignore[no-any-return]


def last_result(request: LlmRequest) -> dict[str, Any]:
    return json.loads(request.messages[-1]["content"][0]["content"])  # type: ignore[no-any-return]


def declaring_detective() -> Any:
    """Tries a holdout first (sent back once), declares three rivals, lists the events, tests them by id."""
    state: dict[str, Any] = {"n": 0, "queue": []}

    def respond(request: LlmRequest) -> LlmResponse:
        state["n"] += 1
        n = state["n"]
        if n == 1:
            p = state["p"] = packet(request)
            state["base"] = {"node": p["focus_node"], "segment": p["root_segment"], "window": p["window"]}
            fake = {"log": "log_deploys", "ref": "x", "ts": p["root_onset"], "kind": "deploy", "description": "x"}
            return reply(n, "holdout_check", {"event": fake, **state["base"], "hypothesis": "h", "prediction": "p"})
        if n == 2:
            assert "declare hypotheses first" in last_result(request)["error"]
            declared = [
                card("H1", event_ref="ps_payco_degraded", statement="the payment provider degraded"),
                card("H2", event_ref="dep_android-app_8.3.0", statement="the android release broke checkout"),
                card("H3", kind="recurring", statement="this hour always dips"),
            ]
            return reply(n, "propose_hypotheses", {"hypotheses": declared}, "Three rivals.")
        if n == 3:
            assert last_result(request)["ids"] == ["H1", "H2", "H3"]
            ew = state["p"]["event_window"]
            args = {"start": ew["start"], "end": ew["end"], "covering": state["p"]["root_segment"]}
            return reply(n, "list_events", {**args, "hypothesis": "h", "prediction": "p"})
        if n == 4:
            events = {e["ref"]: e for e in last_result(request)["data"]["events"]}
            state["queue"] = [("H2", events["dep_android-app_8.3.0"]), ("H1", events["ps_payco_degraded"])]
        if state["queue"]:
            hid, ev = state["queue"].pop(0)
            args = {"event": ev, **state["base"], "hypothesis": "h", "prediction": "p", "hypothesis_id": hid}
            return reply(n, "holdout_check", args)
        if not state.get("placebo"):
            state["placebo"] = True
            return reply(
                n, "placebo_test", {**state["base"], "hypothesis": "h", "prediction": "p", "hypothesis_id": "H3"}
            )
        return reply(n, "submit_findings", {"verdict": "SUPPORTED_CAUSE", "summary": "done"})

    return respond


def run(
    case: tuple[Graph, Anomaly, datetime], world: WorldPaths, client: Any, profile: Profile
) -> tuple[Findings, Journal]:
    graph, anomaly, as_of = case
    journal = Journal()
    selector = AgentSelector(client, journal, mode="replay", profile=profile)
    runner = Runner(world.world)
    try:
        return investigate(graph, runner, anomaly, as_of, selector=selector), journal
    finally:
        runner.close()


@pytest.mark.e2e
def test_declared_hypotheses_on_s1(case: Any, s1_world: WorldPaths) -> None:
    client = FakeLlmClient(responder=declaring_detective())
    findings, journal = run(case, s1_world, client, HYPOTHESES)
    assert findings.verdict is Verdict.SUPPORTED_CAUSE
    assert findings.root is not None and findings.root.evidence is not None
    assert findings.root.evidence.ref == "ps_payco_degraded"
    assert all("propose_hypotheses" in json.dumps(r.tools) for r in client.requests)
    assert all(r.system.endswith("you never mark a card yourself.\n") for r in client.requests)

    rejected = [r for r in journal.records if r.kind == "rejected"]
    assert len(rejected) == 1 and rejected[0].tool == "holdout_check"
    lines = [r for r in journal.records if r.kind == "hypothesis"]
    declared = [DeclaredHypothesis.model_validate(d) for d in lines[0].args["declared"]]  # type: ignore[index]
    assert [d.id for d in declared] == ["H1", "H2", "H3"] and lines[0].tool == "propose_hypotheses"
    moves = [HypothesisMove.model_validate(r.args["move"]) for r in lines[1:]]  # type: ignore[index]
    final = {m.id: m.status for m in moves}
    assert final == {"H1": "supported", "H2": "ruled_out", "H3": "ruled_out"}
    assert all(m.call_id for m in moves)  # every move came from a judged check of the model's
    calls = [r for r in journal.records if r.kind == "tool_call" and r.tool in ("holdout_check", "placebo_test")]
    assert [c.args["hypothesis_id"] for c in calls] == ["H2", "H1", "H3"]  # type: ignore[index]
    # the trail's checks never carry the card id into the typed inputs
    assert all("hypothesis_id" not in json.dumps(s.data.get("ledger", {})) for s in findings.trail)


@pytest.mark.e2e
def test_undeclared_cards_end_not_tested_and_the_gate_backfills(case: Any, s1_world: WorldPaths) -> None:
    def lazy(request: LlmRequest) -> LlmResponse:
        if len(request.messages) == 1:
            declared = [
                card("H1", statement="a logged change"),
                card("H2", kind="market", decisive_check="market_control"),
            ]
            return reply(1, "propose_hypotheses", {"hypotheses": declared})
        return reply(2, "submit_findings", {"verdict": "HYPOTHESIS", "summary": "unsure"})

    findings, journal = run(case, s1_world, FakeLlmClient(responder=lazy), HYPOTHESES)
    assert findings.verdict is Verdict.SUPPORTED_CAUSE  # Stage 2's backfill decides, as in v1
    moves = [
        HypothesisMove.model_validate(r.args["move"])
        for r in journal.records
        if r.kind == "hypothesis" and r.args and "move" in r.args
    ]
    assert {m.id: m.status for m in moves} == {"H1": "not_tested", "H2": "not_tested"}
