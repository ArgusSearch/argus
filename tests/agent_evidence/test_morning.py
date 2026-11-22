from __future__ import annotations

from datetime import timedelta

from argus.agent.types import ClaimDraft, EffectResult, ProposalView, RunContext, SuccessRule, VerifiedClaim
from argus.contracts.events import Event, IncidentUpdatedPayload
from argus.contracts.findings import Verdict, Window
from argus.contracts.graph import Graph
from argus.evidence import EvidenceStore
from argus.narrator.morning import AgentMorning, AgentReportClaim, build_morning_report
from argus.narrator.run_queries import RunWindow, run_query


def test_morning_kpis_use_verified_claims_and_visible_proposal_state(
    store: EvidenceStore, ctx: RunContext, graph: Graph
) -> None:
    as_of = ctx.as_of
    hour = as_of - timedelta(hours=2)
    scope = {"country": "DE", "platform": "android", "provider": "PayCo"}
    interval = Window(start=hour, end=hour)
    observed = store.dispatch(
        ctx, "get_series", {"node": "payment_success_rate", "segment": scope, "window": interval.model_dump()}
    ).fact_handles[0]
    claim = store.verify(
        ctx,
        ClaimDraft(
            kind="observed",
            subject="payment_success_rate",
            segment=scope,
            window=interval,
            fact_ids=[observed.id],
            text="Observed payment success",
        ),
    )
    assert isinstance(claim, VerifiedClaim)
    incident_id = "INC-0001"
    update = Event.make(
        ctx.through_seq,
        as_of,
        IncidentUpdatedPayload(
            id=incident_id,
            title="An unsupported EUR 123456 forecast",
            state="open",
            verdict=Verdict.SUPPORTED_CAUSE,
            root_node=claim.subject,
            segment=scope,
            direction="down",
            severity_eur=123456,
            change="opened",
        ),
    )
    action = ProposalView(
        id="act_0001",
        digest="digest",
        state="AWAIT_OPERATOR",
        run_id=ctx.run_id,
        incident_ref=incident_id,
        playbook_id="rollback_pacer",
        action="Roll back the pacer",
        scope={"country": ["DE", "FR"]},
        effective_at=as_of + timedelta(hours=4),
        expires_at=as_of + timedelta(hours=1),
        success_rule=SuccessRule(
            node="pacing_ratio",
            scope={"country": ["DE", "FR"]},
            rule="Pacing returns to band",
            hours=3,
        ),
        evidence_refs=claim.receipts,
    )
    future = claim.model_copy(update={"claim_id": "future", "as_of": as_of + timedelta(hours=1)})
    empty = claim.model_copy(update={"claim_id": "empty", "receipts": []})
    read_windows = []

    def project(window: RunWindow) -> AgentMorning:
        read_windows.append(window)
        return AgentMorning(
            [AgentReportClaim(item, incident_id) for item in (claim, future, empty)],
            [action],
        )

    window = RunWindow(ctx.stream, ctx.through_seq, (update,))
    report, _ = build_morning_report(window, [], graph, lambda _: False, project)
    assert read_windows == [window]
    assert "123456" not in report.markdown
    claims = [line for line in report.lines if line.id.startswith("agent:claim:")]
    (line,) = claims
    assert "60.00%" in line.text and line.incident_id == incident_id
    (receipt,) = line.receipts
    (ref,) = claim.receipts
    assert receipt.id == ref.key() and receipt.href == f"/agent/receipts/{ref.key()}"
    assert store.inspect_receipt(ctx, ref) is not None
    assert store.rerun_receipt(ctx, ref)[1]

    pending = next(line for line in report.lines if line.id == f"agent:action:{action.id}")
    assert pending.section == "asks" and pending.receipts == [receipt]
    assert "DE/FR" in pending.text
    activity = run_query(window, "activity")
    assert activity is not None and activity.rows == [report.activity.model_dump()]

    effect = EffectResult(
        state="VERIFIED", checked_at=as_of + timedelta(hours=1), receipt_refs=claim.receipts, summary="Pacing restored."
    )
    performed = action.model_copy(update={"state": "VERIFIED", "effect": effect})
    earlier, _ = build_morning_report(window, [], graph, lambda _: False, lambda _: AgentMorning(actions=[performed]))
    assert all(not item.id.startswith("agent:action:") for item in earlier.lines)
    later_window = RunWindow(
        ctx.stream,
        ctx.through_seq + 1,
        (
            update,
            update.model_copy(
                update={"seq": ctx.through_seq + 1, "sim_ts": effect.checked_at},
            ),
        ),
    )
    later, _ = build_morning_report(
        later_window, [], graph, lambda _: False, lambda _: AgentMorning(actions=[performed])
    )
    verified = next(line for line in later.lines if line.id == f"agent:action:{action.id}")
    assert verified.section == "decided" and "Verified" in verified.text
