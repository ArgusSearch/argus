"""PROPOSE and AWAIT_OPERATOR: the host turns an admitted cause into a proposal through lane C's service.

The model never names actuator parameters. After the runtime files an incident whose admitted verdict is
SUPPORTED_CAUSE, the host asks lane C's `RemediationService` for the one executable playbook
(`rollback_pacer`) with the receipts of the run's own supporting checks; the service derives scope, versions
and times from the incident and the world, or rejects. Every service transition becomes an activity record.
"""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING

from argus.agent.journal import Journal
from argus.agent.memory import cause_kind_for, configured_memory, matching_precedent
from argus.agent.types import CaseMemory, CaseNote, Precedent, ReceiptLink, Rejection, RunContext, Stage
from argus.contracts.findings import Incident, Verdict
from argus.remediation.playbooks import ROOT_NODES

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
    def __init__(self, journal: Journal, service: RemediationService, memory: CaseMemory | None = None) -> None:
        self.journal = journal
        self.service = service
        self._memory = memory
        self._pending: dict[str, CaseNote] = {}
        self._proposed: dict[str, CaseNote] = {}
        self._memory_lock = Lock()

    def publish(self, event: RemediationEvent) -> None:
        proposal = event.proposal
        if event.kind == "action_proposed":
            with self._memory_lock:
                note = self._pending.get(proposal.incident_ref)
                if note is not None:
                    self._proposed[proposal.id] = note
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
        if event.kind in ("action_decided", "effect_checked"):
            self._remember_decision(event)

    def _remember_decision(self, event: RemediationEvent) -> None:
        proposal = event.proposal
        run = self.journal.runs.get(proposal.run_id)
        if run is None or run.mode == "replay" or self._memory is None:
            return
        with self._memory_lock:
            note = self._proposed.get(proposal.id)
            if proposal.state != "APPLYING" or event.kind == "effect_checked":
                self._proposed.pop(proposal.id, None)
        if note is None:
            return
        decision = (
            "expired" if proposal.state == "EXPIRED" else (proposal.decision.decision if proposal.decision else "none")
        )
        try:
            self._memory.remember(
                note.model_copy(
                    update={
                        "sim_ts": event.sim_ts,
                        "decision": decision,
                        "effect": proposal.effect.state if proposal.effect else None,
                    }
                )
            )
        except Exception:
            self.journal.add(
                "memory",
                STAGES[event.kind],
                event.sim_ts,
                proposal.run_id,
                text="Case memory could not save the operator outcome.",
                incident_id=proposal.incident_ref,
                action_id=proposal.id,
                role="operator",
            )

    def _memory_allows(self, ctx: RunContext, note: CaseNote, segment: dict[str, str]) -> bool:
        if self._memory is None:
            return True
        try:
            notes = self._memory.recall(
                root_node=note.root_node, segment=segment, cause_kind=note.cause_kind, as_of=ctx.as_of
            )
        except Exception:
            self.journal.add(
                "memory",
                "PROPOSE",
                ctx.as_of,
                ctx.run_id,
                incident_id=ctx.incident_id,
                role="operator",
                text="Case memory unavailable. Applying the usual proposal policy.",
            )
            return True
        policy, remembered = matching_precedent(notes, PLAYBOOK, note.cause_ref)
        if remembered is not None:
            when = remembered.sim_ts.isoformat(sep=" ", timespec="minutes")
            text = {
                "suppress_denied": f"Watching without proposing another rollback. The operator denied it at {when}.",
                "suppress_no_effect": "Watching without another rollback. The prior rollback had no effect.",
                "propose_with_precedent": "An earlier approved rollback had a verified effect.",
                "propose": f"The operator denied a rollback of an earlier version at {when}.",
            }[policy]
            precedent = Precedent(
                case_id=remembered.case_id,
                sim_ts=remembered.sim_ts,
                cause=remembered.cause_ref or "unknown",
                playbook_id=remembered.playbook_id,
                decision=remembered.decision,
                effect=remembered.effect,
                policy=policy,
                note=text,
            )
            self.journal.add(
                "memory",
                "PROPOSE",
                ctx.as_of,
                ctx.run_id,
                incident_id=ctx.incident_id,
                role="operator",
                text=text,
                args=precedent.model_dump(mode="json"),
            )
        return policy in ("propose", "propose_with_precedent")

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
        if run.mode != "replay" and self._memory is None:
            self._memory = configured_memory()
        root = incident.findings.root
        cause_ref = root.evidence.ref if root and root.evidence else None
        cause_kind = cause_kind_for(cause_ref)
        note = None
        if self._memory is not None and root and root.node in ROOT_NODES and cause_kind == "deploy:ad-pacer":
            receipt_ids = {link.receipt_id for link in evidence}
            note = CaseNote(
                case_id=incident.id,
                sim_ts=ctx.as_of,
                fingerprint=incident.fingerprint,
                root_node=root.node,
                segment_dims=sorted(root.segment),
                verdict=incident.verdict.value,
                cause_kind=cause_kind,
                cause_ref=cause_ref,
                playbook_id=PLAYBOOK,
                deciding_checks=sorted(
                    {step.tool for step in incident.findings.trail if receipt_ids & set(step.receipts)}
                ),
            )
            if not self._memory_allows(ctx, note, root.segment):
                return
            with self._memory_lock:
                self._pending[incident.id] = note
        try:
            result = self.service.propose(ctx, incident.id, PLAYBOOK, evidence)
        finally:
            if note is not None:
                with self._memory_lock:
                    self._pending.pop(incident.id, None)
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
