"""PROPOSE and AWAIT_OPERATOR: the host turns an admitted cause into a proposal through lane C's service.

The model never names actuator parameters. After the runtime files an incident whose admitted verdict is
SUPPORTED_CAUSE, the host asks lane C's `RemediationService` for the one executable playbook
(`rollback_pacer`) with the receipts of the run's own supporting checks; the service derives scope, versions
and times from the incident and the world, or rejects. Every service transition becomes an activity record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from argus.agent.journal import Journal
from argus.agent.types import ReceiptLink, Rejection, RunContext, Stage
from argus.contracts.findings import Incident, Verdict

if TYPE_CHECKING:
    from argus.remediation import RemediationEvent, RemediationService

PLAYBOOK = "rollback_pacer"
STAGES: dict[str, Stage] = {
    "action_proposed": "PROPOSE",
    "action_decided": "AWAIT_OPERATOR",
    "action_applied": "ACT",
    "effect_checked": "VERIFY",
}


def supporting_receipts(incident: Incident) -> list[str]:
    """Receipts of the checks that carry the admitted cause: the events listed and the consistent holdout."""
    evidence = incident.findings.root.evidence if incident.findings.root else None
    out: list[str] = []
    for step in incident.findings.trail:
        ledger = step.data.get("ledger") or {}
        event = step.data.get("event") or {}
        if step.tool == "list_events" or (
            step.tool == "holdout_check"
            and ledger.get("outcome") == "consistent"
            and evidence is not None
            and event.get("ref") == evidence.ref
        ):
            out += [r for r in step.receipts if r not in out]
    return out


class Proposer:
    def __init__(self, journal: Journal, service: RemediationService) -> None:
        self.journal = journal
        self.service = service

    def publish(self, event: RemediationEvent) -> None:
        self.journal.add(
            event.kind,
            STAGES[event.kind],
            event.sim_ts,
            event.proposal.run_id,
            actor=event.actor,
            role="operator",
            text=event.text,
            incident_id=event.proposal.incident_ref,
            action_id=event.proposal.id,
            receipt_links=event.receipt_links,
        )

    def on_incident(self, incident: Incident, change: str) -> None:
        """Called by the runtime after it filed or updated an incident."""
        if change not in ("opened", "reopened") or incident.verdict is not Verdict.SUPPORTED_CAUSE:
            return
        anomaly = incident.findings.anomaly_id
        run = next((r for r in reversed(self.journal.runs.values()) if r.anomaly_id == anomaly), None)
        if run is None:
            return  # Stage 2 alone filed it: no agent run to cite
        ctx = RunContext(
            run_id=run.run_id,
            stream=self.journal.stream,
            through_seq=0,
            world_revision="factual",
            as_of=incident.findings.as_of,
            anomaly_id=anomaly,
            incident_id=incident.id,
            kind="investigate",
            mode=run.mode,
        )
        evidence = [
            ReceiptLink(run_id=run.run_id, world_revision="factual", receipt_id=r)
            for r in supporting_receipts(incident)
        ]
        result = self.service.propose(ctx, incident.id, PLAYBOOK, evidence)
        if isinstance(result, Rejection):
            self.journal.add(
                "gate",
                "PROPOSE",
                incident.findings.as_of,
                run.run_id,
                text=f"no executable action: {result.detail}",
                incident_id=incident.id,
                role="operator",
            )
