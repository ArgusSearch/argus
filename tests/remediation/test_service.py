"""Proposal service: derived parameters, one decision per proposal, durable state across a restart."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from argus.agent.types import Decision, ProposalView, Rejection
from argus.contracts.findings import IncidentState, Verdict
from argus.remediation import ProposalConflict, ProposalNotFound, RemediationEvent, RemediationService

from .conftest import EFFECTIVE, context, evidence

AS_OF = datetime(2026, 11, 20, 2)
Make = Callable[..., Any]


def propose(service: RemediationService, run_id: str = "run_0001") -> ProposalView:
    view = service.propose(context(AS_OF, run_id), "INC-0001", "rollback_pacer", evidence(run_id))
    assert isinstance(view, ProposalView), view
    return view


def approve(at: datetime = datetime(2026, 11, 20, 3)) -> Decision:
    return Decision(decision="approve", principal="operator", at=at)


def deny(at: datetime = datetime(2026, 11, 20, 3)) -> Decision:
    return Decision(decision="deny", principal="operator", at=at)


def test_proposal_is_derived_from_the_incident_and_the_deploy_log(make_service: Make) -> None:
    service, _, _ = make_service()
    view = propose(service)
    assert view.state == "AWAIT_OPERATOR" and view.id == "act_0001"
    assert view.playbook_id == "rollback_pacer"
    assert view.scope == {"country": ["DE", "FR"]}
    assert view.effective_at == EFFECTIVE and view.expires_at == datetime(2026, 11, 20, 23)
    assert view.action == (
        "Roll the ad pacer back from 1.7.0 to 1.6 for the DE and FR budget lines from 2026-11-21 00:00 UTC."
    )
    assert view.digest.startswith("sha256:") and len(view.digest) == 71
    assert view.success_rule.comparator == "untreated_twin" and view.success_rule.hours == 3
    deploy = view.evidence_refs[-1]
    assert (deploy.run_id, deploy.world_revision, deploy.receipt_id) == ("act_0001", "factual", "e1")
    receipt = service.receipt(deploy)
    assert receipt is not None and "dep_ad-pacer_1.7.0" in receipt.sql
    assert service.rerun(deploy) == (receipt.result_hash, True)


def test_the_same_incident_yields_the_same_proposal(make_service: Make) -> None:
    service, _, _ = make_service()
    first = propose(service)
    again = propose(service, run_id="run_0009")  # e.g. the runtime re-ran after a restart
    assert again == first
    assert [v.id for v in service.proposals()] == ["act_0001"]


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"playbook_id": "drop_database"}, "policy"),
        ({"ctx": context(AS_OF, revision="act_0001-treated")}, "policy"),
        ({"evidence": []}, "missing_check"),
        ({"evidence": evidence("run_0002")}, "invalid"),
        ({"incident_id": "INC-0099"}, "invalid"),
    ],
)
def test_invalid_proposals_are_rejected(make_service: Make, args: dict[str, Any], reason: str) -> None:
    service, _, _ = make_service()
    call = {"ctx": context(AS_OF), "incident_id": "INC-0001", "playbook_id": "rollback_pacer", "evidence": evidence()}
    result = service.propose(**(call | args))
    assert isinstance(result, Rejection) and result.reason == reason
    assert service.proposals() == []


def test_only_a_supported_cause_can_be_acted_on(make_service: Make) -> None:
    service, _, incidents = make_service()
    incident = incidents["INC-0001"]
    incidents["INC-0001"] = incident.model_copy(
        update={"findings": incident.findings.model_copy(update={"verdict": Verdict.HYPOTHESIS})}
    )
    result = service.propose(context(AS_OF), "INC-0001", "rollback_pacer", evidence())
    assert isinstance(result, Rejection) and result.reason == "missing_check"


def test_denial_is_final_and_its_retry_is_idempotent(make_service: Make) -> None:
    service, _, _ = make_service()
    view = propose(service)
    denied = service.decide(view.id, view.digest, deny(), "key-deny-0001")
    assert denied.state == "DENIED" and denied.decision is not None and denied.decision.principal == "operator"
    assert service.decide(view.id, view.digest, deny(), "key-deny-0001") == denied
    with pytest.raises(ProposalConflict, match="already DENIED"):
        service.decide(view.id, view.digest, approve(), "key-approve-01")
    assert not (service.root / "branches").exists()  # nothing ran


def test_stale_digest_and_unknown_id(make_service: Make) -> None:
    service, _, _ = make_service()
    view = propose(service)
    with pytest.raises(ProposalConflict, match="stale"):
        service.decide(view.id, "sha256:" + "0" * 64, approve(), "key-approve-01")
    with pytest.raises(ProposalNotFound):
        service.decide("act_9999", view.digest, approve(), "key-approve-01")
    assert service.get(view.id) == view


def test_late_approval_expires_the_proposal(make_service: Make) -> None:
    service, _, _ = make_service()
    view = propose(service)
    with pytest.raises(ProposalConflict, match="expired"):
        service.decide(view.id, view.digest, approve(datetime(2026, 11, 20, 23, 30)), "key-approve-01")
    assert service.get(view.id).state == "EXPIRED"


def test_the_clock_expires_an_undecided_proposal(make_service: Make) -> None:
    service, _, _ = make_service()
    propose(service)
    assert service.holds_clock()
    assert service.tick(datetime(2026, 11, 20, 23)) == []
    (expired,) = service.tick(datetime(2026, 11, 21, 0))
    assert expired.state == "EXPIRED" and not service.holds_clock()


def test_a_resolved_incident_makes_the_approval_stale(make_service: Make) -> None:
    service, _, incidents = make_service()
    view = propose(service)
    incidents["INC-0001"].state = IncidentState.RESOLVED
    with pytest.raises(ProposalConflict, match="resolved"):
        service.decide(view.id, view.digest, approve(), "key-approve-01")
    assert service.get(view.id).state == "EXPIRED"


def test_approval_applies_once_and_repeats_return_the_same_result(make_service: Make) -> None:
    activated: list[tuple[Path, str]] = []
    events: list[RemediationEvent] = []
    service, _, _ = make_service(activate=lambda path, rev: activated.append((path, rev)), publish=events.append)
    view = propose(service)
    applied = service.decide(view.id, view.digest, approve(), "key-approve-01")
    assert applied.state == "APPLYING"  # the decision's own answer; the worker ran inline in this test
    now = service.get(view.id)
    assert now is not None and now.state == "APPLIED"
    assert service.decide(view.id, view.digest, approve(), "key-approve-01") == now
    with pytest.raises(ProposalConflict, match="already APPLIED"):
        service.decide(view.id, view.digest, approve(), "key-approve-02")
    with pytest.raises(ProposalConflict):
        service.decide(view.id, view.digest, deny(), "key-approve-01")
    assert len(activated) == 1 and activated[0][1] == "act_0001-treated"
    assert service.active_world() == activated[0]
    execution = service.store.execution(view.id)
    assert execution is not None and execution.activated and not execution.noop
    assert execution.past_receipt is not None and service.rerun(execution.past_receipt) is not None
    assert [e.kind for e in events] == ["action_proposed", "action_decided", "action_applied"]
    assert [j["to_state"] for j in service.store.journal(view.id)] == ["AWAIT_OPERATOR", "APPLYING", "APPLIED"]


def test_concurrent_approvals_execute_exactly_once(make_service: Make) -> None:
    activated: list[str] = []
    service, _, _ = make_service(activate=lambda path, rev: activated.append(rev), background=True)
    view = propose(service)
    outcomes: list[str] = []
    barrier = threading.Barrier(4)

    def click(n: int) -> None:
        barrier.wait()
        try:
            service.decide(view.id, view.digest, approve(), f"key-click-{n:04d}")
            outcomes.append("ok")
        except ProposalConflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=click, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    service.wait()
    assert sorted(outcomes) == ["conflict", "conflict", "conflict", "ok"]
    assert activated == ["act_0001-treated"]
    branches = [p for p in (service.root / "branches").iterdir()]
    assert len(branches) == 1 and not branches[0].name.startswith(".")


def test_restart_during_apply_finishes_the_same_execution(make_service: Make, monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, _ = make_service()
    view = propose(service)
    # The server dies right after the decision committed: the worker never ran.
    monkeypatch.setattr(service, "_start", lambda proposal_id: None)
    service.decide(view.id, view.digest, approve(), "key-approve-01")
    assert service.get(view.id).state == "APPLYING"
    service.close()
    monkeypatch.undo()

    activated: list[str] = []
    restarted, _, _ = make_service(activate=lambda path, rev: activated.append(rev))
    after = restarted.get(view.id)
    assert after is not None and after.state == "APPLIED" and after.digest == view.digest
    assert activated == ["act_0001-treated"]
    # A second restart reuses the published branch and points the new runtime at it again.
    third, _, _ = make_service(activate=lambda path, rev: activated.append(rev))
    assert third.get(view.id) == after
    assert activated == ["act_0001-treated", "act_0001-treated"]
    assert len(list((restarted.root / "branches").iterdir())) == 1


def test_restart_keeps_a_pending_proposal(make_service: Make) -> None:
    service, _, _ = make_service()
    view = propose(service)
    service.close()
    restarted, _, _ = make_service()
    assert restarted.get(view.id) == view
    assert propose(restarted, run_id="run_0004") == view


def test_a_refused_execution_is_reported_not_retried(make_service: Make, tmp_path: Path) -> None:
    service, _, _ = make_service()
    view = propose(service)
    (tmp_path / "branches").mkdir(exist_ok=True)
    # Point the simulator at a world without its configuration: it refuses, nothing is published.
    service.world = tmp_path / "missing" / "world.duckdb"
    service.decide(view.id, view.digest, approve(), "key-approve-01")
    failed = service.get(view.id)
    assert failed is not None and failed.state == "INCONCLUSIVE"
    assert failed.effect is not None and failed.effect.summary.startswith("not applied:")
    assert service.active_world() is None
