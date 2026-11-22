"""The proposal service (lane C side of `argus.agent.types.ProposalService`) and its simulated-clock worker.

```
propose  -> AWAIT_OPERATOR --deny--> DENIED
                   |  \\--clock past expires_at--> EXPIRED
                approve (operator, matching digest, before expiry)
                   v
               APPLYING --simulator--> APPLIED --clock reaches effective_at--> VERIFYING
                                                                                  |
                         twin contrast + incident resolved -> VERIFIED, else NO_EFFECT | INCONCLUSIVE
```

Nothing here is reachable by the model: `propose` derives every parameter from the incident and the world,
`decide` takes an authenticated operator's `Decision`, and `tick` is driven by the runtime's clock. The state
lives in SQLite next to the factual world, so a restarted server finds the same proposals and branches.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from argus.agent.types import (
    Decision,
    EffectResult,
    ProposalView,
    ReceiptLink,
    Rejection,
    RunContext,
    VerifiedClaim,
)
from argus.contracts.findings import Incident, IncidentState, Receipt, Window
from argus.remediation import effect
from argus.remediation.executor import ExecutionFailed, execute, switch_world
from argus.remediation.models import (
    FACTUAL,
    PLAYBOOKS,
    Execution,
    ProposalConflict,
    ProposalNotFound,
    RemediationEvent,
)
from argus.remediation.playbooks import BASE_PACER, derive_rollback, sentence
from argus.remediation.store import ActionStore
from argus.semantic.runner import Runner

HOUR = timedelta(hours=1)
LAG = timedelta(hours=2)
# The incident lifecycle needs a few calm hours after the measured window; past this the effect is INCONCLUSIVE.
VERIFY_DEADLINE = timedelta(hours=12)
# The runtime reads the first treated row one hour and five minutes after the effective hour.
SWITCH_DEADLINE = HOUR

log = logging.getLogger(__name__)

Activate = Callable[[Path, str], None]
Publish = Callable[[RemediationEvent], None]


def world_identity(world: Path) -> str:
    """Identity of a generated world: its public manifest (row counts, window, generation time)."""
    manifest = world.parent / "manifest.json"
    data = manifest.read_bytes() if manifest.exists() else str(world.resolve()).encode()
    return hashlib.sha256(data).hexdigest()


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def treated_revision(proposal_id: str) -> str:
    return f"{proposal_id}-treated"


class RemediationService:
    def __init__(
        self,
        world: str | Path,
        *,
        incidents: Callable[[str], Incident | None],
        clock: Callable[[], datetime | None],
        activate: Activate | None = None,
        publish: Publish | None = None,
        state_dir: Path | None = None,
        background: bool = True,
    ) -> None:
        self.world = Path(world)
        self.identity = world_identity(self.world)
        manifest_path = self.world.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        self.world_end = datetime.fromisoformat(manifest["world_end"]) if "world_end" in manifest else None
        self.root = (state_dir or self.world.parent / "remediation") / self.identity[:12]
        self.branches = self.root / "branches"
        self.store = ActionStore(self.root / "actions.sqlite")
        self._incidents = incidents
        self._clock = clock
        self._activate = activate
        self._publish = publish
        self._background = background
        self._runners: dict[str, Runner] = {}
        self._lock = threading.Lock()
        self._workers: dict[str, threading.Thread] = {}
        self.recover()

    @classmethod
    def for_runtime(cls, runtime: Any, **kwargs: Any) -> RemediationService:
        """Wire the service to a `argus.runtime.loop.Runtime`: its incidents, its clock and its runner."""

        def incidents(incident_id: str) -> Incident | None:
            with runtime.lock:
                found = runtime.book.incidents.get(incident_id)
                return found.model_copy(deep=True) if found else None

        def activate(world: Path, revision: str) -> None:
            with runtime.lock:
                switch_world(runtime.runner, world)

        return cls(runtime.world, incidents=incidents, clock=lambda: runtime.as_of, activate=activate, **kwargs)

    # ------------------------------------------------------------------ ProposalService

    def propose(
        self, ctx: RunContext, incident_id: str, playbook_id: str, evidence: list[ReceiptLink]
    ) -> ProposalView | Rejection:
        if playbook_id not in PLAYBOOKS:
            return Rejection(reason="policy", detail=f"no executable playbook {playbook_id!r}; known: {PLAYBOOKS}")
        if ctx.world_revision != FACTUAL:
            return Rejection(reason="policy", detail="actions apply to the factual world only, once")
        if not evidence:
            return Rejection(reason="missing_check", detail="a proposal cites the run's evidence for the cause")
        if any(link.run_id != ctx.run_id or link.world_revision != ctx.world_revision for link in evidence):
            return Rejection(reason="invalid", detail="evidence must come from this run and world revision")
        incident = self._incidents(incident_id)
        if incident is None:
            return Rejection(reason="invalid", detail=f"no visible incident {incident_id}")
        derived = derive_rollback(incident, self._runner(FACTUAL), ctx.as_of)
        if isinstance(derived, Rejection):
            return derived
        rule = effect.success_rule(derived.countries)
        if self.world_end is not None and derived.effective_at + rule.hours * HOUR > self.world_end:
            return Rejection(reason="policy", detail="the world ends before the effect could be measured")
        scope = {"country": derived.countries}
        identity = _digest(
            {
                "world": self.identity,
                "fingerprint": incident.fingerprint,
                "playbook": playbook_id,
                "scope": scope,
                "from_version": derived.from_version,
                "effective_at": derived.effective_at,
            }
        )

        def make(seq: int) -> ProposalView:
            proposal_id = f"act_{seq:04d}"
            deploy = ReceiptLink(run_id=proposal_id, world_revision=FACTUAL, receipt_id="e1")
            refs = [*evidence, deploy]
            digest = _digest(
                {
                    "run_id": ctx.run_id,
                    "world_revision": ctx.world_revision,
                    "world": self.identity,
                    "incident": incident.id,
                    "fingerprint": incident.fingerprint,
                    "evidence": [link.key() for link in refs],
                    "deploy_hash": derived.receipt.result_hash,
                    "playbook": playbook_id,
                    "scope": scope,
                    "from_version": derived.from_version,
                    "to_version": BASE_PACER,
                    "effective_at": derived.effective_at,
                    "expires_at": derived.expires_at,
                    "success_rule": rule.model_dump(),
                }
            )
            return ProposalView(
                id=proposal_id,
                digest=digest,
                state="AWAIT_OPERATOR",
                run_id=ctx.run_id,
                incident_ref=incident.id,
                playbook_id=playbook_id,
                action=sentence(derived),
                scope=scope,
                effective_at=derived.effective_at,
                expires_at=derived.expires_at,
                success_rule=rule,
                evidence_refs=refs,
            )

        view, created = self.store.insert(identity, make, ctx.as_of, [(FACTUAL, derived.receipt)])
        if created:
            self._emit("action_proposed", ctx.as_of, "host", f"Proposed: {view.action}", view, view.evidence_refs)
        return view

    def get(self, proposal_id: str) -> ProposalView | None:
        return self.store.get(proposal_id)

    def proposals(self) -> list[ProposalView]:
        return self.store.all()

    def decide(self, proposal_id: str, digest: str, decision: Decision, idempotency_key: str) -> ProposalView:
        """Record an operator's decision. Raises ProposalNotFound (404) or ProposalConflict (409)."""
        view = self.store.get(proposal_id)
        if view is None:
            raise ProposalNotFound(proposal_id)
        if view.state != "AWAIT_OPERATOR":
            same = (
                view.decision is not None
                and view.decision.decision == decision.decision
                and view.digest == digest
                and self.store.decision_key(proposal_id) == idempotency_key
            )
            if same:
                return view  # a retry of the decision that was recorded: same answer, nothing runs twice
            raise ProposalConflict(f"{proposal_id} is already {view.state}")
        if digest != view.digest:
            raise ProposalConflict(f"stale proposal: {proposal_id} has a different digest now")
        if decision.at > view.expires_at:
            self._expire(view, decision.at, "approval window closed")
            raise ProposalConflict(f"{proposal_id} expired at {view.expires_at:%Y-%m-%d %H:%M}")
        if decision.decision == "approve":
            incident = self._incidents(view.incident_ref)
            if incident is None:
                raise ProposalConflict(f"{view.incident_ref} is not visible in this run")
            if incident.state is IncidentState.RESOLVED:
                self._expire(view, decision.at, f"{incident.id} resolved before the approval")
                raise ProposalConflict(f"{incident.id} is resolved; the proposal is stale")
        to_state = "APPLYING" if decision.decision == "approve" else "DENIED"
        moved = self.store.transition(
            proposal_id,
            {"AWAIT_OPERATOR"},
            to_state,
            decision.at,
            decision=decision,
            decision_key=idempotency_key,
            detail={"principal": decision.principal},
        )
        if moved is None:  # another request decided first: answer as that decision's retry, or conflict
            return self.decide(proposal_id, digest, decision, idempotency_key)
        verb = "approved" if decision.decision == "approve" else "denied"
        self._emit("action_decided", decision.at, "operator", f"{decision.principal} {verb} {proposal_id}", moved)
        if to_state == "APPLYING":
            self._start(proposal_id)
        return moved

    # ------------------------------------------------------------------ clock

    def tick(self, as_of: datetime) -> list[ProposalView]:
        """Advance every proposal on the simulated clock. Call once per runtime tick, after the lifecycle step."""
        changed = []
        for view in self.store.all():
            if view.state == "AWAIT_OPERATOR" and as_of > view.expires_at:
                moved = self._expire(view, as_of, "nobody decided before the approval window closed")
            elif view.state == "APPLIED" and as_of >= view.effective_at:
                moved = self.store.transition(view.id, {"APPLIED"}, "VERIFYING", as_of)
                if moved is not None:
                    moved = self._verify(moved, as_of) or moved
            elif view.state == "VERIFYING":
                moved = self._verify(view, as_of)
            else:
                moved = None
            if moved is not None:
                changed.append(moved)
        return changed

    def holds_clock(self) -> bool:
        """True while a proposal waits for an operator or the simulator: replay and live pacing pause here."""
        return any(v.state in ("AWAIT_OPERATOR", "APPLYING") for v in self.store.all())

    def active_world(self) -> tuple[Path, str] | None:
        """The treated branch the runtime reads, if an action was applied; else None (the factual world)."""
        for view in reversed(self.store.all()):
            execution = self.store.execution(view.id)
            if execution is not None and execution.activated:
                return Path(execution.branch) / "world.duckdb", execution.world_revision
        return None

    # ------------------------------------------------------------------ receipts

    def receipt(self, link: ReceiptLink) -> Receipt | None:
        return self.store.receipt(link)

    def rerun(self, link: ReceiptLink) -> tuple[str, bool] | None:
        """Re-run a stored receipt on its own world revision. (hash, matches) or None when unknown."""
        found = self.store.receipt(link)
        if found is None:
            return None
        _, fresh = self._runner(link.world_revision).query(found.sql, found.as_of, purpose=f"re-run of {link.key()}")
        return fresh.result_hash, fresh.result_hash == found.result_hash

    # ------------------------------------------------------------------ lifecycle of the service

    def recover(self) -> None:
        """After a restart: finish interrupted executions and point the runtime at the applied branch."""
        active = self.active_world()
        if active is not None and self._activate is not None:
            self._activate(*active)
        for view in self.store.all():
            if view.state == "APPLYING":
                self._start(view.id)

    def wait(self, timeout: float | None = 300) -> None:
        for thread in list(self._workers.values()):
            thread.join(timeout)

    def close(self) -> None:
        self.wait()
        with self._lock:
            for runner in self._runners.values():
                runner.close()
            self._runners.clear()

    # ------------------------------------------------------------------ internals

    def now(self) -> datetime | None:
        return self._clock()

    def _runner(self, revision: str) -> Runner:
        with self._lock:
            runner = self._runners.get(revision)
            if runner is None:
                if revision == FACTUAL:
                    path = self.world
                else:
                    proposal_id = revision.removesuffix("-treated")
                    execution = self.store.execution(proposal_id)
                    if execution is None or execution.world_revision != revision:
                        raise ProposalNotFound(f"no world revision {revision}")
                    path = Path(execution.branch) / "world.duckdb"
                runner = self._runners[revision] = Runner(path)
            return runner

    def _emit(
        self,
        kind: Any,
        sim_ts: datetime,
        actor: Any,
        text: str,
        view: ProposalView,
        links: list[ReceiptLink] | None = None,
    ) -> None:
        if self._publish is None:
            return
        try:
            self._publish(
                RemediationEvent(
                    kind=kind, sim_ts=sim_ts, actor=actor, text=text, proposal=view, receipt_links=links or []
                )
            )
        except Exception:
            log.exception("publishing %s for %s failed", kind, view.id)

    def _expire(self, view: ProposalView, as_of: datetime, reason: str) -> ProposalView | None:
        moved = self.store.transition(view.id, {"AWAIT_OPERATOR"}, "EXPIRED", as_of, detail={"reason": reason})
        if moved is not None:
            self._emit("action_decided", as_of, "host", f"{view.id} expired: {reason}", moved)
        return moved

    def _start(self, proposal_id: str) -> None:
        if not self._background:
            self._apply(proposal_id)
            return
        with self._lock:
            running = self._workers.get(proposal_id)
            if running is not None and running.is_alive():
                return
            thread = threading.Thread(target=self._apply, args=(proposal_id,), name=f"remediate-{proposal_id}")
            self._workers[proposal_id] = thread
            thread.start()

    def _fail(self, view: ProposalView, reason: str, at: datetime, execution: Execution | None = None) -> None:
        result = EffectResult(state="INCONCLUSIVE", checked_at=at, summary=reason)
        moved = self.store.transition(
            view.id, {"APPLYING"}, "INCONCLUSIVE", at, execution=execution, effect=result, detail={"reason": reason}
        )
        if moved is not None:
            self._emit("effect_checked", at, "host", f"{view.id}: {reason}", moved)

    def _apply(self, proposal_id: str) -> None:
        view = self.store.get(proposal_id)
        if view is None or view.state != "APPLYING" or view.decision is None:
            return
        decided_at = view.decision.at
        countries = view.scope["country"]
        try:
            branch = execute(
                self.branches,
                world=self.world,
                proposal_id=view.id,
                digest=view.digest,
                countries=countries,
                to_version=BASE_PACER,
                effective_at=view.effective_at,
                decided_at=decided_at,
            )
        except (ExecutionFailed, OSError) as exc:
            log.exception("remediation %s failed", proposal_id)
            self._fail(view, f"not applied: {exc}", decided_at)
            return
        revision = treated_revision(view.id)
        execution = Execution(
            world_revision=revision,
            branch=str(branch.path),
            noop=bool(branch.result["noop"]),
            lines=list(branch.result["lines"]),
            rows_replaced=int(branch.result["rows"]["inserted"]),
        )
        self.store.set_execution(view.id, execution)

        # The pre-action evidence, re-run on the treated branch: the same hash proves the past is unchanged.
        end = decided_at.replace(minute=0, second=0, microsecond=0) - LAG + HOUR
        sql = effect.pacing_sql(countries, end - 24 * HOUR, end)
        _, before = self._runner(FACTUAL).query(sql, decided_at, purpose="pacing in scope before the action")
        _, again = self._runner(revision).query(sql, decided_at, purpose="the same query on the treated branch")
        past = self.store.add_receipt(view.id, FACTUAL, before)
        self.store.add_receipt(view.id, revision, again)
        execution = execution.model_copy(update={"past_receipt": past})
        if again.result_hash != before.result_hash:
            self._fail(view, "the treated branch changed data before the decision", decided_at, execution)
            return
        now = self.now()
        if now is not None and now > view.effective_at + SWITCH_DEADLINE:
            self._fail(view, "the runtime had already read the effective hour; the branch was not used", now, execution)
            return
        if self._activate is not None:
            self._activate(branch.world, revision)
        execution = execution.model_copy(update={"activated": True})
        moved = self.store.transition(view.id, {"APPLYING"}, "APPLIED", now or decided_at, execution=execution)
        if moved is not None:
            what = "changed nothing (no line on the faulty pacer)" if execution.noop else "applied"
            self._emit(
                "action_applied",
                now or decided_at,
                "host",
                f"{view.id} {what}: {execution.rows_replaced} future ads rows replaced from "
                f"{view.effective_at:%Y-%m-%d %H:%M}",
                moved,
                [past],
            )

    def _verify(self, view: ProposalView, as_of: datetime) -> ProposalView | None:
        execution = self.store.execution(view.id)
        if execution is None:
            return None
        countries = view.scope["country"]
        deadline = view.effective_at + VERIFY_DEADLINE
        verdict = effect.judge(
            self._runner(execution.world_revision), self._runner(FACTUAL), countries, view.effective_at, as_of
        )
        if verdict is None:
            if as_of <= deadline:
                return None
            verdict = effect.Verdict("INCONCLUSIVE", "the measured hours did not arrive in time")
        if verdict.state == "VERIFIED":
            incident = self._incidents(view.incident_ref)
            if incident is None or incident.state is not IncidentState.RESOLVED:
                if as_of <= deadline:
                    return None  # the contrast holds; wait for the incident lifecycle to confirm recovery
                verdict = effect.Verdict(
                    "INCONCLUSIVE",
                    f"pacing recovered against the twin, but {view.incident_ref} did not resolve",
                    verdict.treated,
                    verdict.untreated,
                    verdict.controls,
                )
            else:
                verdict = effect.Verdict(
                    "VERIFIED",
                    f"{verdict.summary}; {incident.id} resolved",
                    verdict.treated,
                    verdict.untreated,
                    verdict.controls,
                )
        result = self._effect(view, execution, verdict, as_of)
        moved = self.store.transition(view.id, {"VERIFYING"}, result.state, as_of, effect=result)
        if moved is not None:
            self._emit("effect_checked", as_of, "host", f"{view.id}: {result.summary}", moved, result.receipt_refs)
        return moved

    def _effect(
        self, view: ProposalView, execution: Execution, verdict: effect.Verdict, as_of: datetime
    ) -> EffectResult:
        links: list[ReceiptLink] = []
        claims: list[VerifiedClaim] = []
        where = "/".join(view.scope["country"])
        window = Window(start=view.effective_at, end=view.effective_at + (view.success_rule.hours - 1) * HOUR)
        if verdict.treated is not None and verdict.untreated is not None:
            t_link = self.store.add_receipt(view.id, execution.world_revision, verdict.treated.receipt)
            u_link = self.store.add_receipt(view.id, FACTUAL, verdict.untreated.receipt)
            links += [t_link, u_link]
            span = f"{window.start:%Y-%m-%d %H:%M}-{window.end:%H:%M}"
            for n, (series, link, revision, label, kind) in enumerate(
                (
                    (verdict.treated, t_link, execution.world_revision, "treated world", "recovered"),
                    (verdict.untreated, u_link, FACTUAL, "untreated twin", "observed"),
                ),
                start=1,
            ):
                value = round(series.aggregate, 4)
                claims.append(
                    VerifiedClaim(
                        claim_id=f"{view.id}:c{n}",
                        kind=kind,  # type: ignore[arg-type]
                        subject="pacing_ratio",
                        window=window,
                        as_of=as_of,
                        world_revision=revision,
                        value=value,
                        unit="ratio",
                        display=f"{where} pacing ratio {value:.2f} [{link.receipt_id}] in the {label}, {span}",
                        receipts=[link],
                    )
                )
        if verdict.controls is not None:
            links.append(self.store.add_receipt(view.id, execution.world_revision, verdict.controls[0]))
            links.append(self.store.add_receipt(view.id, FACTUAL, verdict.controls[1]))
        if execution.past_receipt is not None:
            links.append(execution.past_receipt)
        return EffectResult(
            state=verdict.state,  # type: ignore[arg-type]
            checked_at=as_of,
            summary=verdict.summary,
            claims=claims,
            receipt_refs=links,
        )
