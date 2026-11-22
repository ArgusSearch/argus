"""Apply the genuine S4 investigation through the authenticated action boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scripts.agent_eval.bundle import read_bundle

from argus.agent.investigate import AgentSelector
from argus.agent.journal import Journal
from argus.agent.provider import Cassette, ReplayClient
from argus.agent.types import ProposalView, ReceiptLink, Rejection, RunContext
from argus.contracts.findings import IncidentState
from argus.runtime.loop import Runtime
from mockmart.sim import WorldConfig
from mockmart.world import generate

if TYPE_CHECKING:
    from argus.remediation.service import RemediationService

pytestmark = pytest.mark.e2e
CASSETTES = Path(__file__).resolve().parents[2] / "fixtures" / "agent" / "v1" / "cassettes"
type Case = tuple[Runtime, RemediationService, ProposalView, TestClient]


@pytest.fixture(scope="module")
def s4_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate("s4", WorldConfig(seed=1), tmp_path_factory.mktemp("eval-remediation")).world


@pytest.fixture
def case(s4_path: Path, tmp_path: Path) -> Iterator[Case]:
    from argus.remediation.api import create_router
    from argus.remediation.service import RemediationService

    pin = json.loads((CASSETTES / "accepted.json").read_bytes())["s4"]
    recording = read_bundle(CASSETTES / "s4", expected_digest=pin, presentation=False)
    provider = ReplayClient(Cassette(recording.documents["turns.jsonl"]))
    journal = Journal()
    selector = AgentSelector(provider, journal, mode="replay")
    runtime = Runtime(s4_path, selector=selector)
    service = RemediationService.for_runtime(runtime, state_dir=tmp_path / "remediation", background=False)
    try:
        for as_of in runtime.ticks():
            runtime.tick(as_of)
            if runtime.book.incidents:
                break
        assert not list(provider.unused())
        (investigation,) = journal.runs.values()
        assert investigation.status == "done" and investigation.anomaly_id
        (incident,) = runtime.book.incidents.values()
        assert runtime.as_of is not None
        scope = RunContext(
            run_id=investigation.run_id,
            stream=journal.stream,
            through_seq=runtime.bus.history[-1].seq,
            world_revision="factual",
            as_of=runtime.as_of,
            anomaly_id=investigation.anomaly_id,
            incident_id=incident.id,
            mode="replay",
        )
        evidence = [
            ref
            for item in journal.records
            if item.kind == "tool_result" and item.tool == "holdout_check" and item.receipt_links
            for ref in item.receipt_links
        ]
        assert evidence
        swapped = evidence[0].model_copy(update={"run_id": "unrelated"})
        assert isinstance(service.propose(scope, incident.id, "rollback_pacer", [swapped]), Rejection)
        proposal = service.propose(scope, incident.id, "rollback_pacer", evidence)
        assert isinstance(proposal, ProposalView) and proposal.state == "AWAIT_OPERATOR"
        app = FastAPI()
        app.include_router(create_router(service))
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            yield runtime, service, proposal, client
    finally:
        service.close()
        runtime.runner.close()


def authorize(client: TestClient) -> dict[str, str]:
    from argus.remediation.api import CSRF_HEADER

    response = client.post("/agent/operator/session")
    assert response.status_code == 200
    return {CSRF_HEADER: response.json()["csrf_token"]}


def choice(proposal: ProposalView, verb: str) -> tuple[str, dict[str, str]]:
    return (
        f"/agent/actions/{proposal.id}/{verb}",
        {"digest": proposal.digest, "idempotency_key": f"eval-{verb}-once"},
    )


def test_e09_unauthorized_wrong_digest_and_denied_actions_do_not_mutate_world(case: Case) -> None:
    runtime, service, proposal, client = case
    original_world = runtime.runner.world_path
    url, body = choice(proposal, "approve")
    assert client.post(url, json=body).status_code == 403
    headers = authorize(client)
    assert client.post(url, json={**body, "digest": "sha256:" + "0" * 64}, headers=headers).status_code == 409
    deny, denied_body = choice(proposal, "deny")
    response = client.post(deny, json=denied_body, headers=headers)
    assert response.status_code == 200 and response.json()["state"] == "DENIED"
    assert client.post(deny, json=denied_body, headers=headers).json() == response.json()
    assert client.post(url, json=body, headers=headers).status_code == 409
    assert service.store.execution(proposal.id) is None and runtime.runner.world_path == original_world


def test_e09_late_approval_cannot_execute(case: Case) -> None:
    runtime, service, proposal, client = case
    original_world = runtime.runner.world_path
    runtime.as_of = proposal.expires_at + timedelta(hours=1)
    url, body = choice(proposal, "approve")
    response = client.post(url, json=body, headers=authorize(client))
    assert response.status_code == 409
    expired = service.get(proposal.id)
    assert expired is not None and expired.state == "EXPIRED"
    assert service.store.execution(proposal.id) is None and runtime.runner.world_path == original_world


def test_e10_approved_s4_rollback_resolves_against_the_untouched_twin(case: Case) -> None:
    runtime, service, proposal, client = case
    original_world = runtime.runner.world_path
    pre_action = {key: receipt.result_hash for key, receipt in runtime.runner.receipts.items()}
    with original_world.open("rb") as source:
        untouched_sha = hashlib.file_digest(source, "sha256").hexdigest()
    assert service.store.execution(proposal.id) is None
    url, body = choice(proposal, "approve")
    headers = authorize(client)
    approved = client.post(url, json=body, headers=headers)
    assert approved.status_code == 200
    retry = client.post(url, json=body, headers=headers)
    assert retry.status_code == 200
    action = ProposalView.model_validate(retry.json())
    assert action.decision and action.decision.principal == "operator"
    assert action.scope == {"country": ["DE", "FR"]}
    execution = service.store.execution(proposal.id)
    assert execution and runtime.runner.world_path != original_world
    assert len([row for row in service.store.journal(proposal.id) if row["to_state"] == "APPLIED"]) == 1

    approved_at = runtime.as_of
    assert approved_at
    for as_of in runtime.ticks():
        if as_of <= approved_at:
            continue
        runtime.tick(as_of)
        service.tick(as_of)
        final = service.get(proposal.id)
        assert final is not None
        if final.effect is not None:
            break
    final = service.get(proposal.id)
    assert final is not None and final.state == "VERIFIED" and final.effect is not None
    incident = runtime.book.incidents[proposal.incident_ref]
    assert incident.state == IncidentState.RESOLVED and incident.resolved_at is not None
    treated, untouched = final.effect.claims
    assert treated.value is not None and untouched.value is not None
    assert abs(treated.value - 1) <= 0.15
    assert abs(untouched.value - 1) >= 0.20 and abs(treated.value - 1) <= 0.5 * abs(untouched.value - 1)
    assert len({link.world_revision for link in final.effect.receipt_refs}) == 2
    for ref in final.effect.receipt_refs:
        assert isinstance(ref, ReceiptLink)
        result = service.rerun(ref)
        assert result is not None and result[1]
    for receipt_id, original_hash in pre_action.items():
        assert runtime.runner.rerun(receipt_id) == (original_hash, True)
    with original_world.open("rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == untouched_sha
