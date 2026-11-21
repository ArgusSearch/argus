"""Synthetic S4 tape exercises the offline playback cut without a provider or simulator."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from shutil import copytree
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from argus.agent.types import INTERFACE_VERSION, ActivityRecord, Decision, EffectResult, ProposalView, ReceiptLink
from argus.api.hub import EventHub
from argus.api.recording import FIXTURES, load_recording
from argus.api.state import RunState
from argus.contracts.events import EventType, TickPayload
from argus.demo.agent import _build_timeline
from argus.demo.api import create_router
from argus.demo.bundle import ReceiptProof, read_bundle, receipt_keys
from argus.demo.contracts import AgentDemoState
from argus.demo.playback import ControlError, Playback
from argus.graph.store import load_seed_graph

QUESTION = "Could higher traffic explain the spend?"


def _json(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def recording_dir(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, ProposalView]:
    path = tmp_path_factory.mktemp("synthetic-agent-recording")
    legacy = load_recording(FIXTURES / "s4")
    snapshot = legacy.incidents[0]
    prefix = [event for event in legacy.events if event.seq <= snapshot.seq]
    clock = prefix[-1].sim_ts
    applied_at = clock + timedelta(hours=1)
    checked_at = clock + timedelta(hours=6)
    ticks = [event for event in legacy.events if event.type is EventType.TICK and event.seq > snapshot.seq]
    morning = next(
        tick for tick in ticks if tick.sim_ts > checked_at and TickPayload.model_validate(tick.payload).hour.hour == 8
    )
    approval_events = [event for event in ticks if event.seq <= morning.seq]
    root = snapshot.incident.findings.root
    assert root is not None and root.change_pct.receipt
    proof_id = root.change_pct.receipt
    investigation_proof = ReceiptLink(run_id="investigate", world_revision="factual", receipt_id=proof_id)
    treated = ReceiptLink(run_id="effect", world_revision="after-action", receipt_id=proof_id)
    untreated = ReceiptLink(run_id="effect", world_revision="factual", receipt_id=proof_id)
    pending = ProposalView(
        id="rollback",
        digest="sha256:synthetic",
        state="AWAIT_OPERATOR",
        run_id="investigate",
        incident_ref=snapshot.incident.id,
        playbook_id="rollback_pacer",
        action="Roll back the DE and FR ad pacer.",
        scope={"country": ["DE", "FR"]},
        effective_at=applied_at,
        expires_at=applied_at,
        success_rule={"node": "pacing_ratio", "scope": {"country": ["DE", "FR"]}, "rule": "Pacing in band", "hours": 3},
        evidence_refs=[investigation_proof],
    )
    effect = EffectResult(
        state="VERIFIED", checked_at=checked_at, summary="Synthetic effect", receipt_refs=[treated, untreated]
    )
    approved = pending.model_copy(
        update={
            "state": "VERIFIED",
            "decision": Decision(decision="approve", principal="operator", at=clock),
            "effect": effect,
        }
    )
    denied = pending.model_copy(
        update={"state": "DENIED", "decision": Decision(decision="deny", principal="operator", at=clock)}
    )
    announcement = ActivityRecord(
        seq=3,
        run_id="investigate",
        kind="action_proposed",
        stage="PROPOSE",
        actor="host",
        sim_ts=clock,
        action_id=pending.id,
    )
    decide = ActivityRecord(
        seq=4,
        run_id="investigate",
        kind="action_decided",
        stage="AWAIT_OPERATOR",
        actor="operator",
        sim_ts=clock,
        action_id=pending.id,
    )
    activity = [
        ActivityRecord(
            seq=1,
            run_id="investigate",
            kind="tool_call",
            stage="ACT",
            actor="model",
            sim_ts=clock,
            tool="list_events",
        ),
        ActivityRecord(
            seq=2,
            run_id="investigate",
            kind="tool_result",
            stage="OBSERVE",
            actor="host",
            sim_ts=clock,
            receipt_links=[investigation_proof],
        ),
        announcement,
    ]
    approved_activity = [
        decide,
        ActivityRecord(
            seq=5,
            run_id="investigate",
            kind="action_applied",
            stage="PROPOSE",
            actor="host",
            sim_ts=applied_at,
            action_id=pending.id,
        ),
        ActivityRecord(
            seq=6,
            run_id="effect",
            kind="effect_checked",
            stage="VERIFY",
            actor="host",
            sim_ts=checked_at,
            action_id=pending.id,
            receipt_links=[treated, untreated],
        ),
    ]
    ask = {
        "question": QUESTION,
        "through_seq": prefix[-1].seq,
        "response": {
            "status": "answered",
            "answer": "The recorded check points to pacing.",
            "claims": [],
            "receipt_links": [_dump(investigation_proof)],
            "activity_cursor": 2,
        },
    }
    graph = _dump(load_seed_graph())
    base_docs = {
        "events.jsonl": [_dump(event) for event in prefix],
        "activity.jsonl": [_dump(record) for record in activity],
        "actions.json": [_dump(pending)],
        "graph.json": graph,
        "incidents.json": [_dump(snapshot.incident)],
        "ask.jsonl": [ask],
        "turns.jsonl": [
            {
                "key": "investigate:example:1",
                "request_sha": "0" * 64,
                "response": {
                    "model": "synthetic",
                    "content": [{"type": "text", "text": "Synthetic fixture only."}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            }
        ],
    }
    required = set(receipt_keys(list(base_docs.values())))
    receipts = {receipt.id: receipt for receipt in legacy.receipts}

    def proof(key: str) -> dict[str, Any]:
        receipt = receipts[key.rsplit("/", 1)[-1]]
        return _dump(ReceiptProof(receipt=receipt, verified_at_capture=False))

    base_docs["receipts.json"] = {key: proof(key) for key in required}
    approve_docs = {
        "approve/events.jsonl": [_dump(event) for event in approval_events],
        "approve/activity.jsonl": [_dump(record) for record in approved_activity],
        "approve/actions.json": [_dump(approved)],
        "approve/receipts.json": {key: proof(key) for key in (treated.key(), untreated.key())},
    }
    needed = set(receipt_keys(approve_docs["approve/events.jsonl"])) - required
    approve_docs["approve/receipts.json"].update({key: proof(key) for key in needed})
    documents = (
        base_docs
        | approve_docs
        | {
            "deny/events.jsonl": [],
            "deny/activity.jsonl": [_dump(decide)],
            "deny/actions.json": [_dump(denied)],
        }
    )
    artifacts = {}
    for name, document in documents.items():
        data = b"".join(_json(row) + b"\n" for row in document) if name.endswith("jsonl") else _json(document)
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        artifacts[name] = _sha(data)
    manifest = {
        "schema_version": 1,
        "provenance": "synthetic_test",
        "scenario": "s4",
        "source_commit": "0" * 40,
        "seed": 1,
        "interface_version": INTERFACE_VERSION,
        "models": ["synthetic"],
        "world": {"days": 3},
        "prompt_sha": "1" * 64,
        "tools_sha": "2" * 64,
        "graph_sha": _sha(_json(graph)),
        "artifacts": artifacts,
    }
    digest = _sha(_json(manifest))
    (path / "manifest.json").write_bytes(_json(manifest | {"bundle_sha": digest}))
    return path, digest, pending


def test_cold_playback_holds_clock_and_repeats_ask_receipt_and_effect(recording_dir: tuple) -> None:
    path, sha, proposal = recording_dir

    def cold() -> tuple:
        now = 0.0
        playback = Playback(clock=lambda: now)
        tape = _build_timeline(read_bundle(path, "s4", sha, allow_synthetic=True))
        started = playback.start(tape, 1.0)
        assert isinstance(started, AgentDemoState) and started.run_id
        run_id = started.run_id
        early = playback.agent_view(run_id)
        assert early.ask(QUESTION).status == "unavailable"
        with pytest.raises(ControlError):
            playback.decide(run_id, proposal.id, "approve", proposal.digest, "click")

        now += 10_000
        pending = playback.agent_view(run_id)
        assert pending.state.status == "awaiting_approval" and pending.state.elapsed_ms == 50_000
        assert pending.actions[0].state == "AWAIT_OPERATOR"
        assert not any(record.kind in {"action_decided", "effect_checked"} for record in pending.activity)
        answer = pending.ask("Could  HIGHER traffic explain the spend", proposal.incident_ref)
        proof = pending.receipts[answer.receipt_links[0].key()]
        assert pending.ask("an unseen question").status == "unavailable"
        assert pending.ask(QUESTION, "different-case").status == "unavailable"
        assert not any(key.startswith("effect/") for key in pending.receipts)
        now += 42
        assert playback.state() == pending.state
        for action in ("skip", "resume", "pause"):
            with pytest.raises(ControlError):
                playback.control(action)
        with pytest.raises(ControlError):
            playback.decide(run_id, proposal.id, "approve", "old-digest", "click")
        with pytest.raises(ControlError):
            playback.decide("replaced-run", proposal.id, "approve", proposal.digest, "click")

        decision = playback.decide(run_id, proposal.id, "approve", proposal.digest, "click")
        assert decision.elapsed_ms == 50_000
        assert playback.decide(run_id, proposal.id, "approve", proposal.digest, "click") == decision
        assert playback.agent_view(run_id).actions[0].state == "APPLYING"
        with pytest.raises(ControlError):
            playback.decide(run_id, proposal.id, "deny", proposal.digest, "different-click")
        now += 20
        assert playback.agent_view(run_id).actions[0].state == "APPLIED"
        now += 20
        done = playback.agent_view(run_id)
        assert done.state.status == "completed" and done.actions[0].state == "VERIFIED"
        effect = done.actions[0].effect
        assert effect and done.state.sim_ts > effect.checked_at
        assert all(link.key() in done.receipts for link in effect.receipt_refs)
        assert done.receipts[answer.receipt_links[0].key()] == proof
        assert tape.report is not None
        report = tape.report.report
        action_line = next(line for line in report.lines if line.id == f"agent:action:{proposal.id}")
        assert {ref.id for ref in action_line.receipts} >= {ref.key() for ref in effect.receipt_refs}
        assert report.activity.until == effect.checked_at
        return (run_id, done.activity, answer, proof, effect, report)

    first, second = cold(), cold()
    assert first[0] != second[0]
    assert first[1:] == second[1:]


def test_http_deny_and_reconnect_stop_at_cut(recording_dir: tuple) -> None:
    path, sha, proposal = recording_dir
    timeline = _build_timeline(read_bundle(path, "s4", sha, allow_synthetic=True))
    now = 0.0
    playback = Playback(clock=lambda: now)
    app = FastAPI()
    app.include_router(
        create_router(
            EventHub(RunState(timeline.graph)), playback=playback, allow_agent=True, agent_loader=lambda _: timeline
        )
    )
    with TestClient(app) as client:
        state = client.post("/demo/start", json={"scenario": "s4", "variant": "agent"}).json()
        assert state["variant"] == "agent" and state["through_seq"] > 0
        run_id = state["run_id"]
        params = {"run_id": run_id}
        assert client.post("/demo/control", json={"action": "pause"}).status_code == 409
        assert client.get("/demo/report/morning", params=params).status_code == 404
        now += 50
        held = client.get("/demo/snapshot", params=params).json()
        assert held["state"]["status"] == "awaiting_approval"
        assert held["events"][-1]["seq"] == held["state"]["through_seq"]
        playback.decide(run_id, proposal.id, "deny", proposal.digest, "deny-click")
        now += 500
        assert playback.agent_view(run_id).actions[0].state == "DENIED"
        assert not any(key.startswith("effect/") for key in playback.agent_view(run_id).receipts)
        assert client.get("/demo/report/morning", params=params).status_code == 404
        stream = client.get("/demo/events", params=params, headers={"Last-Event-ID": f"{run_id}:4"}).text
        assert '"kind":"action_proposed"' in stream and "event: complete" in stream
        assert "action_executed" not in stream and "effect_checked" not in stream
        newer = client.post("/demo/control", json={"action": "restart"}, params=params).json()
        assert newer["run_id"] != run_id and newer["decision"] is None
        assert client.get("/demo/snapshot", params=params).status_code == 409
        assert client.get("/demo/events", params=params).status_code == 204

        new_id = newer["run_id"]
        now += 50
        playback.decide(new_id, proposal.id, "approve", proposal.digest, "approve-click")
        now += 40
        report = client.get("/demo/report/morning", params={"run_id": new_id})
        assert report.status_code == 200
        action_line = next(line for line in report.json()["lines"] if line["id"] == f"agent:action:{proposal.id}")
        assert all(ref["href"].endswith(f"?run_id={new_id}") for ref in action_line["receipts"])


def test_manifest_pin_and_provenance_are_required(recording_dir: tuple, tmp_path: Path) -> None:
    path, sha, _ = recording_dir
    with pytest.raises(ValueError, match="does not match"):
        read_bundle(path, "s4", "0" * 64, allow_synthetic=True)
    with pytest.raises(ValueError, match="no live capture provenance"):
        read_bundle(path, "s4", sha)
    dst = tmp_path / "tampered"
    copytree(path, dst)
    with (dst / "approve/activity.jsonl").open("ab") as file:
        file.write(b"\n")
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        read_bundle(dst, "s4", sha, allow_synthetic=True)
