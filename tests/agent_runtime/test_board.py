"""The derived board (src/argus/agent/board.py): built from the sealed v1 recordings, Stage-2 findings and the
playback cursor, never from a model. Served by GET /agent/boards and GET /agent/boards/incident/{id}."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from argus.agent.board import build_board, build_boards, run_of
from argus.agent.types import ActivityRecord, Board, Observation, Precedent, ReceiptLink, RunSummary
from argus.api.app import create_app
from argus.api.sources import LiveSource, ReplaySource
from argus.contracts.findings import Incident, Verdict
from mockmart.world import WorldPaths

REPO = Path(__file__).resolve().parents[2]
V1 = REPO / "fixtures" / "agent" / "v1"


def records(path: Path) -> list[ActivityRecord]:
    return [ActivityRecord.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


def incidents(path: Path) -> list[Incident]:
    return [Incident.model_validate(raw) for raw in json.loads(path.read_text())]


def by_subject(board: Board) -> dict[str | None, str]:
    return {card.subject: card.status for card in board.hypotheses if card.kind == "event"}


def invariants(board: Board, incident: Incident | None) -> None:
    """The contract the web relies on (docs/ext/agent.md "Board")."""
    assert sum(board.counts.values()) == len(board.hypotheses)
    assert set(board.counts) == {"open", "supported", "ruled_out", "inconclusive", "not_tested"}
    assert [c.id for c in board.hypotheses] == [f"H{i}" for i in range(1, len(board.hypotheses) + 1)]
    for card in board.hypotheses:
        if card.status not in ("open", "not_tested"):
            assert any(check.receipts for check in card.checks), card
    if board.state != "running":
        assert board.counts["open"] == 0
    if incident is None:
        return
    findings = incident.findings
    supported = {c.subject for c in board.hypotheses if c.kind == "event" and c.status == "supported"}
    cause = findings.root.evidence if findings.root is not None else None
    if findings.verdict is Verdict.SUPPORTED_CAUSE and cause is not None:
        assert supported == {cause.ref}
    else:
        assert supported == set()
    statements = {c.statement for c in board.hypotheses if c.status == "ruled_out"}
    subjects = {c.subject for c in board.hypotheses if c.status == "ruled_out"}
    for ruled in findings.ruled_out:
        if ruled.result == "refuted":
            assert (ruled.evidence is not None and ruled.evidence.ref in subjects) or ruled.hypothesis in statements


# ---------------------------------------------------------------------------------------------- sealed v1 bundles


def test_s1_sealed_bundle_shows_one_supported_cause_and_the_rivals_ruled_out() -> None:
    activity = records(V1 / "s1" / "activity.jsonl")
    [incident] = incidents(V1 / "s1" / "incidents.json")
    [board] = build_boards(activity, [incident])
    invariants(board, incident)
    assert (board.agent_run, board.incident_id, board.anomaly_id) == ("run_0001", "INC-0001", "an_0001")
    assert board.profile == "v1" and board.state == "done" and board.through_seq == activity[-1].seq
    events = by_subject(board)
    assert events == {
        "ps_payco_degraded": "supported",
        "dep_android-app_8.3.0": "ruled_out",
        "dep_checkout-service_1.2.6": "ruled_out",
    }
    assert board.counts["supported"] == 1 and board.counts["ruled_out"] >= 4
    kinds = {c.kind: c.status for c in board.hypotheses if c.kind != "event"}
    assert kinds == {"recurring": "ruled_out", "data": "ruled_out", "planned": "ruled_out", "mix": "ruled_out"}
    android = next(c for c in board.hypotheses if c.subject == "dep_android-app_8.3.0")
    [check] = android.checks
    assert (check.by, check.seq, check.step, check.call_id) == ("detective", 7, 9, "run_0001:2")
    assert check.receipts == [ReceiptLink(run_id="run_0001", world_revision="factual", receipt_id="r240")]
    assert "[r240]" in check.summary
    # the checkout deploy was tested only by the gate's backfill: a host check from the trail, no activity seq
    checkout = next(c for c in board.hypotheses if c.subject == "dep_checkout-service_1.2.6")
    assert [(c.by, c.seq, c.step) for c in checkout.checks] == [("host", None, 12)]


def test_s1_board_groups_discarded_paths_and_cost() -> None:
    activity = records(V1 / "s1" / "activity.jsonl")
    [incident] = incidents(V1 / "s1" / "incidents.json")
    [board] = build_boards(activity, [incident])
    assert [(g.phase, g.first_seq, g.last_seq, g.tool_calls) for g in board.groups] == [
        ("opening", 1, 1, 0),
        ("checks", 2, 12, 4),
        ("verdict", 13, 16, 0),
        ("action", 17, 17, 0),
    ]
    assert all(g.status == "done" for g in board.groups)
    assert board.groups[1].summary == "4 check(s): list_events, holdout_check, holdout_check, placebo_test"
    kinds = [d.kind for d in board.discarded]
    assert kinds.count("ruled_out") == board.counts["ruled_out"] and "backfilled" in kinds
    # the closing line's billed total, not the records re-added (one reply left no record with a model)
    finished = next(r for r in activity if r.kind == "run_finished")
    assert board.cost.usd == finished.usd == 0.039186
    assert board.cost.llm_calls == 4 and board.cost.tool_calls == 4 and board.cost.replayed
    assert (board.cost.cap_usd, board.cost.cap_tool_calls) == (0.5, 12)
    [line] = board.cost.lines
    assert (line.phase, line.model, line.llm_calls, line.usd) == ("detective", "claude-sonnet-5-5", 4, 0.039186)
    assert board.critic is None and board.precedents == [] and board.second_opinion is None


def test_s4_sealed_bundle_keeps_a_consistent_rival_inconclusive() -> None:
    activity = records(V1 / "s4" / "activity.jsonl") + records(V1 / "s4" / "approve" / "activity.jsonl")
    [incident] = incidents(V1 / "s4" / "incidents.json")
    [board] = build_boards(activity, [incident])
    invariants(board, incident)
    assert by_subject(board) == {"dep_ad-pacer_1.7.0": "supported", "pacer_adv_01_DE_1.7": "inconclusive"}
    rival = next(c for c in board.hypotheses if c.subject == "pacer_adv_01_DE_1.7")
    assert "dep_ad-pacer_1.7.0" in rival.reason
    others = sorted(c.statement for c in board.hypotheses if c.kind == "other")
    assert others == ["a change in planned spend drove ad_spend", "a change in sessions drove ad_spend"]
    assert [g.phase for g in board.groups] == ["opening", "checks", "verdict", "action", "effect"]
    assert board.cost.usd == 0.045867 and board.cost.llm_calls == 4


@pytest.mark.parametrize("scenario", ["s1", "s4"])
def test_board_is_a_pure_function_of_its_input(scenario: str) -> None:
    activity = records(V1 / scenario / "activity.jsonl")
    found = incidents(V1 / scenario / "incidents.json")
    first = [b.model_dump_json() for b in build_boards(activity, found)]
    assert first == [b.model_dump_json() for b in build_boards(list(activity), list(found))]


def test_cards_appear_open_and_flip_as_the_playback_advances() -> None:
    activity = records(V1 / "s1" / "activity.jsonl")
    [incident] = incidents(V1 / "s1" / "incidents.json")
    final = build_boards(activity, [incident])[0]
    seen: list[tuple[str, str | None]] = []
    for cursor in range(1, len(activity) + 1):
        visible = activity[:cursor]
        # the incident is published with the verdict; before it, only the activity is visible
        shown = [incident] if any(r.kind == "run_finished" for r in visible) else []
        [board] = build_boards(visible, shown)
        invariants(board, shown[0] if shown else None)
        ids = [(c.id, c.subject) for c in board.hypotheses]
        assert ids[: len(seen)] == seen, "card ids stay stable while the run advances"
        seen = ids
        if cursor == 4:  # list_events returned three candidates, none judged yet
            assert board.state == "running" and board.counts["open"] == 3
            assert board.groups[-1].status == "running"
        if cursor == 7:  # the release's holdout came back refuted
            assert by_subject(board)["dep_android-app_8.3.0"] == "ruled_out"
            assert board.counts["open"] == 2
    assert seen == [(c.id, c.subject) for c in final.hypotheses]


# ---------------------------------------------------------------------------------------------- Stage 2 and negatives


@pytest.mark.parametrize("path", ["fixtures", "fixtures/s4", "fixtures/s5"])
def test_stage2_incident_board_needs_no_agent_run(path: str) -> None:
    [incident] = incidents(REPO / path / "incidents.json")
    board = build_board([], None, None, incident=incident)
    invariants(board, incident)
    assert board.profile == "stage2" and board.agent_run is None and board.state == "done"
    assert board.groups == [] and board.cost.usd == 0 and not board.cost.replayed
    assert board.chain is not None
    receipts = {link.run_id for card in board.hypotheses for check in card.checks for link in check.receipts}
    assert receipts == {"stage2"}


def test_a_hypothesis_verdict_has_no_supported_event_and_no_chain() -> None:
    [incident] = incidents(V1 / "s1" / "incidents.json")
    root = incident.findings.root
    assert root is not None
    findings = incident.findings.model_copy(
        update={"verdict": Verdict.HYPOTHESIS, "root": root.model_copy(update={"evidence": None})}
    )
    weaker = incident.model_copy(update={"verdict": Verdict.HYPOTHESIS, "findings": findings})
    board = build_board(records(V1 / "s1" / "activity.jsonl"), None, None, incident=weaker)
    invariants(board, weaker)
    assert by_subject(board)["ps_payco_degraded"] == "inconclusive" and board.chain is None


def test_admitted_cause_takes_precedence_over_a_refuted_holdout_on_another_cut() -> None:
    [incident] = incidents(V1 / "s1" / "incidents.json")
    [*activity, last] = records(V1 / "s1" / "activity.jsonl")
    root = incident.findings.root
    assert root is not None and root.evidence is not None
    off_scope = result(
        last.seq + 1,
        "run_0001:c1",
        "holdout_check",
        "refuted",
        "r999",
        event=root.evidence.model_dump(mode="json"),
        segment={"country": "FR"},
    )
    [board] = build_boards([*activity, last, off_scope], [incident])
    invariants(board, incident)
    assert by_subject(board)[root.evidence.ref] == "supported"


def test_an_agent_run_without_findings_finishes_without_open_cards() -> None:
    activity = records(V1 / "s1" / "activity.jsonl")
    [board] = build_boards(activity, [])
    assert board.state == "done" and board.counts["open"] == 0
    assert by_subject(board) == {
        "ps_payco_degraded": "supported",
        "dep_android-app_8.3.0": "ruled_out",
        "dep_checkout-service_1.2.6": "not_tested",
    }
    assert any(d.kind == "not_tested" for d in board.discarded)


def test_run_of_matches_an_incident_to_its_investigation() -> None:
    activity = records(V1 / "s1" / "activity.jsonl")
    [incident] = incidents(V1 / "s1" / "incidents.json")
    assert run_of(incident, activity) == "run_0001"
    [stage2] = incidents(REPO / "fixtures" / "incidents.json")
    assert run_of(stage2, []) is None


# ---------------------------------------------------------------------------------------------- v2 payloads

AS_OF = datetime(2026, 11, 21, 20)


def rec(seq: int, kind: str, stage: str = "PLAN", **fields: Any) -> ActivityRecord:
    base: dict[str, Any] = {"run_id": "run_0001", "sim_ts": AS_OF, "actor": "host", "anomaly_id": "an_0001"}
    return ActivityRecord.model_validate({"seq": seq, "kind": kind, "stage": stage, **base, **fields})


def result(seq: int, call_id: str, tool: str, outcome: str, receipt: str, **args: Any) -> ActivityRecord:
    link = ReceiptLink(run_id="run_0001", world_revision="factual", receipt_id=receipt)
    obs = Observation(
        call_id=call_id, tool=tool, args=args, outcome=outcome, summary=f"{tool} {outcome}", receipt_refs=[link]
    )
    return rec(seq, "tool_result", "OBSERVE", tool=tool, observation=obs, receipt_links=[link], text=obs.summary)


def test_v2_payloads_feed_model_cards_the_counter_check_and_precedents() -> None:
    event = {"log": "log_deploys", "ref": "dep_x", "description": "x 1.0", "kind": "deploy"}
    usage = {"model": "claude-sonnet-5-5", "input_tokens": 100, "output_tokens": 10, "usd": 0.01}
    declared = [
        {"id": "A", "statement": "the deploy broke it", "kind": "event", "event_ref": "dep_x", "decisive_check": "h"},
        {"id": "B", "statement": "the data is late", "kind": "data", "decisive_check": "check_freshness"},
        {"id": "C", "statement": "only android", "kind": "segment", "parent": "A", "decisive_check": "sql_check"},
    ]
    precedent = Precedent(
        case_id="INC-0001",
        sim_ts=datetime(2026, 11, 20, 2),
        cause="deploy:x",
        playbook_id="rollback_x",
        decision="deny",
        effect=None,
        policy="suppress_denied",
        note="Not proposing the rollback again: the operator denied it.",
    )
    activity = [
        rec(1, "run_started", "TRIAGE", text="started"),
        rec(2, "thought", actor="model", text="three rivals", **usage),
        rec(3, "hypothesis", tool="propose_hypotheses", args={"declared": declared}),
        rec(4, "tool_call", "ACT", actor="model", tool="sql_check", args={"hypothesis_id": "C", "sql": "SELECT 1"}),
        result(5, "run_0001:1", "sql_check", "fails", "r5"),
        rec(6, "hypothesis", args={"move": {"id": "C", "status": "ruled_out", "reason": "the cut fails"}}),
        rec(7, "tool_call", "ACT", actor="model", tool="holdout_check", args={"hypothesis_id": "A", "event": event}),
        result(8, "run_0001:2", "holdout_check", "consistent", "r8", event=event),
        rec(9, "gate", "VERIFY", text="verdict SUPPORTED_CAUSE (model claimed SUPPORTED_CAUSE)"),
        rec(10, "thought", "VERIFY", actor="model", text="checking", model="claude-opus-5-5", usd=0.05),
        rec(11, "tool_call", "ACT", actor="model", role="skeptic", tool="placebo_test", args={}),
        result(12, "run_0001:c1", "placebo_test", "unusual", "r12"),
        rec(13, "critic", "VERIFY", args={"verdict": "upheld", "downgrade": False, "reason": "no rule fired"}),
        rec(14, "run_finished", "REPORT", text="2 model call(s), USD 0.0600", usd=0.06),
        rec(15, "memory", "PROPOSE", args=precedent.model_dump(mode="json")),
    ]
    board = build_board(activity, None, None, run_id="run_0001")
    invariants(board, None)
    assert board.profile == "v2" and board.state == "done"
    cards = {c.statement: c for c in board.hypotheses}
    assert [c.source for c in board.hypotheses[:3]] == ["model", "model", "model"]
    assert cards["the deploy broke it"].status == "supported" and cards["the deploy broke it"].subject == "dep_x"
    assert cards["only android"].status == "ruled_out" and cards["only android"].parent == "H1"
    assert [c.call_id for c in cards["only android"].checks] == ["run_0001:1"]
    assert cards["the data is late"].status == "not_tested"
    assert board.critic is not None and board.critic.result == "upheld" and board.critic.attempts == 1
    assert [c.by for c in board.critic.checks] == ["critic"]
    assert board.precedents == [precedent]
    assert "critic" in [g.phase for g in board.groups] and "hypotheses" in [g.phase for g in board.groups]
    assert (board.cost.cap_usd, board.cost.cap_tool_calls) == (0.7, 15)
    phases = {line.phase for line in board.cost.lines}
    assert phases == {"detective", "critic"} and board.cost.usd == 0.06


def test_a_failed_loop_shows_fallback() -> None:
    activity = [
        rec(1, "run_started", "TRIAGE", text="started"),
        rec(2, "fallback", text="baseline_fallback: ProviderUnavailable: down"),
        rec(3, "gate", "VERIFY", text="verdict SUPPORTED_CAUSE"),
        rec(4, "run_finished", "REPORT", text="0 model call(s), USD 0.0000", usd=0.0),
    ]
    run = RunSummary(
        run_id="run_0001", kind="investigate", mode="live", sim_ts=AS_OF, status="fallback", fallback="down"
    )
    board = build_board(activity, None, run)
    assert board.state == "fallback" and board.groups[-1].status == "failed" and not board.cost.replayed


# ---------------------------------------------------------------------------------------------- routes


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("ARGUS_DEMO_BUNDLE", raising=False)
    monkeypatch.delenv("ARGUS_DEMO_BUNDLE_SHA", raising=False)
    return TestClient(create_app(ReplaySource(REPO / "fixtures" / "s4"), start=False), client=("127.0.0.1", 50000))


def resolvable(client: TestClient, board: dict[str, Any], params: dict[str, str]) -> int:
    """Every receipt a card, the chain or a discarded path cites resolves through the agent receipt route."""
    links = [r for card in board["hypotheses"] for check in card["checks"] for r in check["receipts"]]
    links += [r for link in (board["chain"] or {"links": []})["links"] for r in link["receipts"]]
    links += [r for d in board["discarded"] for r in d["receipts"]]
    for link in links:
        path = f"/agent/receipts/{link['run_id']}/{link['world_revision']}/{link['receipt_id']}"
        assert client.get(path, params=params).status_code == 200, path
    return len(links)


def test_the_presentation_serves_its_board_at_the_playback_clock(replay: TestClient) -> None:
    with replay as client:
        assert client.get("/agent/health").json()["board_version"] == "agent-board/1"
        started = client.post("/demo/start", json={"scenario": "s4", "variant": "agent", "speed": 1})
        run = {"run_id": started.json()["run_id"]}
        early = client.get("/agent/boards", params=run).json()
        assert early["boards"] == [] or all(b["state"] in ("running", "done") for b in early["boards"])
        for _ in range(20):
            if client.get("/demo/state").json()["status"] == "awaiting_approval":
                break
            assert client.post("/demo/control", params=run, json={"action": "skip"}).status_code == 200
        body = client.get("/agent/boards", params=run).json()
        [board] = body["boards"]
        assert body["next_cursor"] == board["through_seq"] > 0
        Board.model_validate(board)
        assert board["incident_id"] == "INC-0001" and board["profile"] == "v1"
        assert board["counts"]["supported"] == 1 and board["counts"]["open"] == 0
        assert board["chain"]["text"].startswith("ad-pacer 1.7.0")
        assert resolvable(client, board, run) > 10
        link = board["chain"]["links"][0]["receipts"][0]
        assert client.get(f"/agent/receipts/other-run/factual/{link['receipt_id']}", params=run).status_code == 404
        one = client.get("/agent/boards/incident/INC-0001", params=run).json()
        assert one == board
        assert client.get("/agent/boards/incident/INC-9999", params=run).status_code == 404
        assert board["cost"]["llm_calls"] == 4


def test_plain_replay_serves_the_stage2_board(replay: TestClient) -> None:
    with replay as client:
        assert client.get("/agent/boards/incident/INC-0001").status_code == 404  # not published yet
        assert client.post("/replay", json={"action": "end"}).status_code == 200
        assert client.get("/agent/boards").json() == {"boards": [], "next_cursor": 0}
        board = client.get("/agent/boards/incident/INC-0001").json()
        assert board["profile"] == "stage2" and board["agent_run"] is None
        assert board["counts"]["supported"] == 1
        assert resolvable(client, board, {}) > 10
        link = board["chain"]["links"][0]["receipts"][0]
        assert client.get(f"/agent/receipts/stage2/other-world/{link['receipt_id']}").status_code == 404
        assert client.get("/agent/receipts/stage2/factual/r99999").status_code == 404


@pytest.mark.e2e
def test_a_live_run_with_the_agent_off_serves_the_stage2_board(s1_world: WorldPaths) -> None:
    source = LiveSource(s1_world.world, agent="off")
    for as_of in source.runtime.ticks():
        source.runtime.tick(as_of)
        if source.runtime.book.incidents:
            break
    with TestClient(create_app(source, start=False)) as client:
        health = client.get("/agent/health").json()
        assert (health["profile"], health["features"], health["board_version"]) == ("v1", [], "agent-board/1")
        assert client.get("/agent/boards").json()["boards"] == []
        [incident] = source.incidents()
        board = client.get(f"/agent/boards/incident/{incident.id}").json()
        assert board["profile"] == "stage2" and board["counts"]["open"] == 0
        assert by_subject(Board.model_validate(board))["ps_payco_degraded"] == "supported"
        assert resolvable(client, board, {}) > 10
