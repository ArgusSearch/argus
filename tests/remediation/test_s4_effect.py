"""S4 end to end: Argus finds the pacer rollout, an operator approves the DE/FR rollback, the simulator applies it
from the next budget day, and the effect is verified against the untouched twin and by the incident lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from argus.agent.types import Decision, ProposalView
from argus.contracts.findings import IncidentState
from argus.remediation import RemediationEvent, RemediationService
from argus.remediation.effect import judge
from argus.runtime.loop import Runtime
from argus.semantic.runner import Runner
from mockmart.world import WorldPaths

from .conftest import EFFECTIVE, context, evidence

pytestmark = pytest.mark.e2e


def test_s4_rollback_is_verified_against_the_untouched_twin(s4_world: WorldPaths, tmp_path: Path) -> None:
    runtime = Runtime(s4_world.world)
    twin = Runtime(s4_world.world)  # the same world, never treated
    events: list[RemediationEvent] = []
    service = RemediationService.for_runtime(runtime, state_dir=tmp_path, background=False, publish=events.append)
    proposal: ProposalView | None = None
    switched_at: datetime | None = None
    receipts_before = 0
    try:
        for as_of in runtime.ticks():
            runtime.tick(as_of)
            twin.tick(as_of)
            service.tick(as_of)
            if proposal is None and runtime.book.incidents:
                found = service.propose(context(as_of), "INC-0001", "rollback_pacer", evidence())
                assert isinstance(found, ProposalView)
                proposal = found
            elif proposal is not None and switched_at is None:
                receipts_before = len(runtime.runner.receipts)
                decision = Decision(decision="approve", principal="operator", at=as_of)
                service.decide(proposal.id, proposal.digest, decision, "key-approve-01")
                switched_at = as_of
            current = service.get(proposal.id) if proposal else None
            if current is not None and current.state in ("VERIFIED", "NO_EFFECT", "INCONCLUSIVE"):
                break

        assert proposal is not None and switched_at is not None
        assert proposal.effective_at == EFFECTIVE and switched_at < EFFECTIVE
        final = service.get(proposal.id)
        assert final is not None and final.effect is not None
        assert final.state == "VERIFIED", final.effect.summary
        assert final.effect.checked_at == EFFECTIVE + timedelta(hours=4)  # 3 complete hours after 00:00, lag 2 h

        # The runtime reads the treated branch; its incident resolved through the ordinary lifecycle.
        execution = service.store.execution(proposal.id)
        assert execution is not None and runtime.runner.world_path == Path(execution.branch) / "world.duckdb"
        assert runtime.book.incidents["INC-0001"].state is IncidentState.RESOLVED
        # The untouched twin still burns the DE/FR budgets by mid-morning: its incident stays open.
        assert twin.book.incidents["INC-0001"].state is not IncidentState.RESOLVED

        treated, untreated = final.effect.claims
        assert treated.world_revision == "act_0001-treated" and untreated.world_revision == "factual"
        assert abs(treated.value - 1) <= 0.15  # type: ignore[operator]
        assert abs(untreated.value - 1) >= 0.5  # type: ignore[operator]
        assert "[e" in treated.display
        for link in final.effect.receipt_refs:
            rerun = service.rerun(link)
            assert rerun is not None and rerun[1], link.key()

        # Every receipt Argus minted before the switch re-runs to the same hash on the treated branch.
        for receipt_id in list(runtime.runner.receipts)[:receipts_before]:
            assert runtime.runner.rerun(receipt_id)[1], receipt_id

        assert [e.kind for e in events] == ["action_proposed", "action_decided", "action_applied", "effect_checked"]
        assert [j["to_state"] for j in service.store.journal(proposal.id)] == [
            "AWAIT_OPERATOR",
            "APPLYING",
            "APPLIED",
            "VERIFYING",
            "VERIFIED",
        ]
    finally:
        service.close()
        runtime.runner.close()
        twin.runner.close()


def test_twin_judge_reports_no_effect_and_waits_for_data(s4_world: WorldPaths) -> None:
    """A world compared with itself shows no effect; hours still arriving give no verdict yet."""
    a, b = Runner(s4_world.world), Runner(s4_world.world)
    try:
        assert judge(a, b, ["DE", "FR"], EFFECTIVE, EFFECTIVE + timedelta(hours=3)) is None
        verdict = judge(a, b, ["DE", "FR"], EFFECTIVE, EFFECTIVE + timedelta(hours=4))
        assert verdict is not None and verdict.state == "NO_EFFECT"
        quiet = judge(a, b, ["UK"], EFFECTIVE, EFFECTIVE + timedelta(hours=4))
        assert quiet is not None and quiet.state == "NO_EFFECT"
    finally:
        a.close()
        b.close()
