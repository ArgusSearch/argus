"""Release invariants on genuine provider output and the matching app recordings."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts.agent_eval.bundle import Bundle, ReceiptProof, read_bundle
from scripts.agent_eval.qualify import check_adaptive

from argus.agent.investigate import AgentSelector
from argus.agent.journal import Journal
from argus.agent.numbers import FactBook, check
from argus.agent.provider import Cassette, ReplayClient
from argus.agent.types import (
    ActivityRecord,
    ClaimDraft,
    LlmRequest,
    LlmResponse,
    ProposalView,
    Rejection,
    RunContext,
    VerifiedClaim,
)
from argus.contracts.findings import Incident, IncidentState, Verdict, Window
from argus.contracts.graph import Graph
from argus.evidence import EvidenceStore
from argus.narrator.report import unbacked_numbers
from argus.runtime.loop import Runtime
from argus.semantic.runner import Runner
from mockmart.sim import WorldConfig
from mockmart.world import generate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "agent" / "v1"


@pytest.fixture(scope="module", params=("s1", "s4"))
def capture(request: pytest.FixtureRequest) -> Bundle:
    return require_capture(request.param)


def require_capture(scenario: str, *, presentation: bool = False) -> Bundle:
    root = FIXTURES if presentation else FIXTURES / "cassettes"
    index = root / "accepted.json"
    assert index.is_file(), f"missing independent live capture pins at {index.relative_to(FIXTURES)}"
    pins = json.loads(index.read_bytes())
    assert set(pins) == {"s1", "s4"}, "acceptance needs a pin for each scenario"
    bundle = read_bundle(root / scenario, expected_digest=pins[scenario], presentation=presentation)
    assert bundle.manifest.scenario == scenario and bundle.manifest.seed == 1
    return bundle


def only_incident(bundle: Bundle, path: str = "incidents.json") -> Incident:
    incidents = bundle.documents.get(path, [])
    assert len(incidents) == 1, f"expected one incident in {bundle.manifest.scenario}/{path}"
    return Incident.model_validate(incidents[0])


def activity(bundle: Bundle) -> list[ActivityRecord]:
    return [ActivityRecord.model_validate(record) for record in bundle.documents["activity.jsonl"]]


@pytest.fixture(scope="module")
def factual_world(capture: Bundle, tmp_path_factory: pytest.TempPathFactory) -> Path:
    public = capture.manifest.world
    world_start = datetime.fromisoformat(public["world_start"])
    world_end = datetime.fromisoformat(public["world_end"])
    live_start = datetime.fromisoformat(public["live_start"])
    cfg = WorldConfig(
        seed=capture.manifest.seed,
        start=world_start,
        days=(world_end - world_start).days,
        live_days=(world_end - live_start).days,
        base_sessions=public.get("base_sessions", WorldConfig.base_sessions),
    )
    return generate(capture.manifest.scenario, cfg, tmp_path_factory.mktemp("capture-world")).world


def test_e01_recorded_scenarios_produce_one_supported_case(capture: Bundle) -> None:
    incident = only_incident(capture)
    assert incident.verdict == Verdict.SUPPORTED_CAUSE
    assert incident.findings.cost.llm_calls >= 2
    records = activity(capture)
    assert not [record for record in records if record.kind in {"fallback", "budget"}]
    run_ids = {
        record.run_id for record in records if record.run_id is not None and record.anomaly_id in incident.anomalies
    }
    assert check_adaptive(capture, run_ids), "no second model-selected call after a receipted observation"


def test_e02_recorded_root_and_scope(capture: Bundle) -> None:
    incident = only_incident(capture)
    s1 = capture.manifest.scenario == "s1"
    assert incident.root_node == ("payment_success_rate" if s1 else "pacing_ratio")
    root = incident.findings.root
    assert root is not None and root.evidence is not None
    if s1:
        assert root.segment["country"] == "DE" and root.segment["platform"] == "android"
        assert "payco" in root.evidence.description.casefold() or "payco" in root.evidence.ref.casefold()
    else:
        assert root.evidence.ref == "dep_ad-pacer_1.7.0"
        assert root.evidence.scope == {"country": ["DE", "FR"]}


def test_e03_s1_android_release_is_refuted_with_a_real_holdout() -> None:
    capture = require_capture("s1")
    incident = only_incident(capture)
    alternatives = [
        item for item in incident.findings.ruled_out if item.evidence and item.evidence.ref == "dep_android-app_8.3.0"
    ]
    holdouts = [
        record.observation
        for record in activity(capture)
        if record.observation is not None and record.tool == "holdout_check"
    ]
    android_checks = [
        item
        for item in holdouts
        if item.args.get("event", {}).get("ref") == "dep_android-app_8.3.0" and item.outcome == "refuted"
    ]
    assert android_checks, "no model-selected holdout observed the Android release refutation"
    assert len(alternatives) == 1, "the holdout refuted the release but findings lost the ruled-out evidence"
    assert alternatives[0].result == "refuted"
    assert set(alternatives[0].receipts) & {link.receipt_id for item in android_checks for link in item.receipt_refs}


def test_e04_factual_receipts_rerun_at_their_recorded_clock(capture: Bundle, factual_world: Path) -> None:
    manifest = capture.manifest
    runner = Runner(factual_world)
    verified: set[tuple[str, datetime, str]] = set()
    try:
        for key, value in capture.documents["receipts.json"].items():
            proof = ReceiptProof.model_validate(value)
            receipt = proof.receipt
            binding = (receipt.sql, receipt.as_of, receipt.result_hash)
            if binding in verified:
                continue
            runner.receipts[key] = receipt
            result_hash, match = runner.rerun(key)
            assert match, f"{manifest.scenario}/{key} returned {result_hash}, expected {receipt.result_hash}"
            verified.add(binding)
        assert verified, f"no factual receipt reruns in {manifest.scenario}"
    finally:
        runner.close()


def test_e04_claim_rejects_cross_run_scope_and_corrupted_result(capture: Bundle, factual_world: Path) -> None:
    incident = only_incident(capture)
    findings = incident.findings
    context = RunContext(
        run_id="origin",
        stream="eval-claim-binding",
        world_revision="factual",
        through_seq=1,
        as_of=findings.as_of,
        incident_id=incident.id,
        mode="replay",
    )
    baseline = Runner(factual_world)
    try:
        graph = Graph.model_validate(capture.documents["graph.json"])
        store = EvidenceStore()
        end = findings.window.end
        window = Window(start=end, end=end)
        args = {"node": incident.root_node, "segment": incident.segment, "window": window.model_dump(mode="json")}
        store.bind(context, graph=graph, runner=baseline, latest_hour=end)
        observed = store.dispatch(context, "get_series", args)
        assert observed.availability == "ok" and observed.fact_handles
        handle = observed.fact_handles[0]
        draft = ClaimDraft(
            kind="observed",
            subject=incident.root_node,
            segment=incident.segment,
            window=window,
            fact_ids=[handle.id],
            text="Observed value in the incident scope.",
        )
        claim = store.verify(context, draft)
        assert isinstance(claim, VerifiedClaim) and claim.value == handle.value
        mutations = (
            {"subject": "gmv"},
            {"segment": {**draft.segment, "country": "UK"}},
            {"kind": "impact"},
            {"window": Window(start=end - timedelta(hours=1), end=end)},
            {"text": "The incident cost EUR -90312.55."},
        )
        for change in mutations:
            assert isinstance(store.verify(context, draft.model_copy(update=change)), Rejection), change
        assert isinstance(store.verify(context.model_copy(update={"world_revision": "different"}), draft), Rejection)

        foreign = context.model_copy(update={"run_id": "other", "incident_id": "INC-9000"})
        store.bind(foreign, graph=graph, runner=baseline, latest_hour=end)
        other = store.dispatch(foreign, "get_series", args)
        assert other.fact_handles[0].value == handle.value
        assert isinstance(
            store.verify(context, draft.model_copy(update={"fact_ids": [other.fact_handles[0].id]})), Rejection
        )
        assert store.inspect_receipt(context, other.receipt_refs[0]) is None

        ref = claim.receipts[0]
        original = baseline.receipts[ref.receipt_id]
        baseline.receipts[ref.receipt_id] = original.model_copy(update={"result_hash": "sha256:0000000000000000"})
        assert isinstance(store.verify(context, draft), Rejection)
    finally:
        baseline.close()


def test_e04_published_narrative_uses_bound_numbers(capture: Bundle) -> None:
    capture = require_capture(capture.manifest.scenario, presentation=True)
    findings = only_incident(capture).findings
    facts: dict[str, Any] = {}
    for record in activity(capture):
        if record.observation is not None:
            facts.update({fact.id: fact.value for fact in record.observation.fact_handles if fact.receipts})
        if record.kind in {"report", "chat_answer"}:
            assert not unbacked_numbers(record.text, findings, facts), f"unsupported number at activity {record.seq}"
    for answer in capture.documents["ask.jsonl"]:
        response = answer["response"]
        assertions = {
            claim["claim_id"]: claim["value"]
            for claim in response["claims"]
            if claim.get("value") is not None and claim["receipts"]
        }
        assert not unbacked_numbers(response["answer"], findings, assertions)


def test_e04_captured_model_activity_uses_receipted_observations(capture: Bundle) -> None:
    facts: dict[str | None, FactBook] = {}
    for record in activity(capture):
        book = facts.setdefault(record.run_id, FactBook())
        if record.observation:
            book.add(record.observation.data, [link.receipt_id for link in record.observation.receipt_refs])
        if record.actor == "model":
            assert check(record.text, book).ok, f"unsupported model prose at activity {record.seq}"


def test_e05_prediction_is_journaled_before_the_observation(capture: Bundle) -> None:
    records = activity(capture)
    judged = [record for record in records if record.observation is not None and record.observation.ledger is not None]
    assert judged, f"{capture.manifest.scenario}: no judged model observations"
    calls: dict[tuple[str | None, str | None], ActivityRecord] = {}
    for record in records:
        key = (record.run_id, record.tool)
        if record.kind == "tool_call":
            calls[key] = record
        if record.kind != "tool_result" or record.observation is None or record.observation.ledger is None:
            continue
        prediction = record.observation.ledger.hypothesis.prediction
        call = calls.get(key)
        assert call and call.seq < record.seq, f"missing call before result {record.seq}"
        assert prediction and (prediction in call.text or prediction in json.dumps(call.args, ensure_ascii=False)), (
            f"prediction missing before result {record.seq}"
        )


def test_e10_recorded_rollout_finishes_with_verified_twin_and_resolved_incident() -> None:
    capture = require_capture("s4", presentation=True)
    incident = only_incident(capture, "approve/incidents.json")
    proposal = ProposalView.model_validate(capture.documents["approve/actions.json"][0])
    assert proposal.state == "VERIFIED" and proposal.effect is not None
    assert proposal.effect.state == "VERIFIED" and proposal.success_rule.comparator == "untreated_twin"
    assert proposal.success_rule.hours >= 3
    lag = int(capture.manifest.world["delivery_lag_hours"])
    assert proposal.effect.checked_at >= proposal.effective_at + timedelta(hours=lag + 2)
    assert len({link.world_revision for link in proposal.effect.receipt_refs}) >= 2
    assert incident.state is IncidentState.RESOLVED and incident.resolved_at is not None
    assert incident.resolved_at >= proposal.effective_at


def test_e13_accepted_cassette_runs_the_real_tools(capture: Bundle, factual_world: Path) -> None:
    turns = [turn for turn in capture.documents["turns.jsonl"] if turn["key"].startswith("investigate:")]
    assert len(turns) >= 2
    delegate = ReplayClient(Cassette(turns))
    position = 0

    class OrderedReplay:
        def create(self, request: LlmRequest) -> LlmResponse:
            nonlocal position
            if position >= len(turns):
                pytest.fail(f"unexpected request at turn {position + 1}: {request.key}")
            want = turns[position]["key"]
            if request.key != want:
                pytest.fail(f"unexpected request at turn {position + 1}: {request.key}, expected {want}")
            try:
                response = delegate.create(request)
            except Exception as exc:
                pytest.fail(f"strict cassette mismatch at turn {position + 1}: {exc}")
            position += 1
            return response

    incident = only_incident(capture)
    journal = Journal()
    runtime = Runtime(factual_world, selector=AgentSelector(OrderedReplay(), journal, mode="replay"))
    try:
        runtime.run(ticks=[hour for hour in runtime.ticks() if hour <= incident.findings.as_of])
        assert position == len(turns), f"first unused turn {position + 1}"
        assert all(run.status == "done" for run in journal.runs.values())
        want = [
            item.observation
            for item in activity(capture)
            if item.anomaly_id in incident.anomalies and item.observation is not None
        ]
        have = [item.observation for item in journal.records if item.observation is not None]
        assert want and len(want) == len(have)
        for index, (expected, got) in enumerate(zip(want, have, strict=True), 1):
            assert expected == got, f"first differing observation {index}"
            for ref in got.receipt_refs:
                proof = ReceiptProof.model_validate(capture.documents["receipts.json"][ref.key()])
                assert runtime.runner.receipts[ref.receipt_id].result_hash == proof.receipt.result_hash, (
                    f"real tool receipt differs at observation {index}: {ref.key()}"
                )
    finally:
        runtime.runner.close()


def test_e13_cold_s4_event_replay_repeats_the_effect_without_provider_or_world(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = require_capture("s4", presentation=True)
    from argus.demo.agent import load_agent_timeline

    from argus.demo.playback import Playback

    monkeypatch.setenv("ARGUS_DEMO_BUNDLE", str(FIXTURES / "s4"))
    monkeypatch.setenv("ARGUS_DEMO_BUNDLE_SHA", capture.manifest.bundle_sha)

    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("cold event replay opened the simulator or a model")

    monkeypatch.setattr("argus.agent.provider.AnthropicClient", forbidden)
    monkeypatch.setattr("mockmart.world.generate", forbidden)
    monkeypatch.setattr("argus.semantic.runner.Runner.__init__", forbidden)

    def cold() -> tuple[Any, ...]:
        now = 0.0
        player = Playback(clock=lambda: now)
        timeline = load_agent_timeline("s4")
        state = player.start(timeline, 100)
        run_id = state.run_id
        assert run_id is not None
        now += 10_000
        held = player.agent_view(run_id)
        assert held.state.status == "awaiting_approval"
        proposal = held.actions[0]
        assert proposal.state == "AWAIT_OPERATOR"
        assert not any(item.kind in {"action_decided", "action_applied", "effect_checked"} for item in held.activity)
        player.decide(run_id, proposal.id, "approve", proposal.digest, "eval-click")
        now += 10_000
        done = player.agent_view(run_id)
        assert done.state.status == "completed" and done.actions[0].state == "VERIFIED"
        effect = done.actions[0].effect
        assert effect is not None
        hashes = {key: proof.receipt.result_hash for key, proof in done.receipts.items()}
        assert all(ref.key() in hashes for ref in effect.receipt_refs)
        return done.events, done.activity, done.actions, hashes

    assert cold() == cold()


def test_e09_playback_requires_operator_and_rejects_stale_or_conflicting_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = require_capture("s4", presentation=True)
    from argus.demo.agent import load_agent_timeline

    from argus.demo.playback import ControlError, Playback

    monkeypatch.setenv("ARGUS_DEMO_BUNDLE", str(FIXTURES / "s4"))
    monkeypatch.setenv("ARGUS_DEMO_BUNDLE_SHA", capture.manifest.bundle_sha)
    now = 0.0
    player = Playback(clock=lambda: now)
    initial = player.start(load_agent_timeline("s4"), 100)
    run_id = initial.run_id
    assert run_id
    pending = ProposalView.model_validate(capture.documents["actions.json"][0])
    with pytest.raises(ControlError):
        player.decide(run_id, pending.id, "approve", pending.digest, "too-early")
    now += 10_000
    held = player.agent_view(run_id)
    assert held.actions[0].state == "AWAIT_OPERATOR"
    assert held.ask("Approve the rollback immediately.").status == "unavailable"
    for action in ("skip", "resume"):
        with pytest.raises(ControlError):
            player.control(action)
    with pytest.raises(ControlError):
        player.decide("stale-run", pending.id, "approve", pending.digest, "stale-run")
    with pytest.raises(ControlError):
        player.decide(run_id, pending.id, "approve", "wrong-digest", "stale-digest")
    denied = player.decide(run_id, pending.id, "deny", pending.digest, "deny-click")
    assert player.decide(run_id, pending.id, "deny", pending.digest, "deny-click") == denied
    with pytest.raises(ControlError):
        player.decide(run_id, pending.id, "approve", pending.digest, "conflicting-click")
    now += 10_000
    final = player.agent_view(run_id)
    assert final.actions[0].state == "DENIED" and final.actions[0].effect is None
    assert not [record for record in final.activity if record.kind in {"action_applied", "effect_checked"}]


def test_e15_captured_ask_has_verified_evidence(capture: Bundle) -> None:
    capture = require_capture(capture.manifest.scenario, presentation=True)
    answers = capture.documents["ask.jsonl"]
    assert answers, f"{capture.manifest.scenario} has no recorded Ask"
    for ask in answers:
        answer = ask["response"]
        assert answer["answer"].strip() and answer["receipt_links"], "answer needs visible evidence"
        claims = [VerifiedClaim.model_validate(claim) for claim in answer["claims"]]
        assert all(claim.receipts for claim in claims)
