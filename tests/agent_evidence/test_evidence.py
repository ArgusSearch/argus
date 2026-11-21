from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from argus.agent.types import ClaimDraft, Rejection, RunContext, VerifiedClaim
from argus.api.recording import FIXTURES, load_recording
from argus.contracts.findings import Anomaly, Window
from argus.contracts.graph import Graph
from argus.counterfactual.models import CounterfactualResult, Gap, QueryProof, ReplayReceipt, WorldConfig
from argus.counterfactual.replay import make_plan
from argus.evidence import EvidenceStore
from argus.semantic.runner import Runner

HOUR = datetime(2026, 11, 20, 18)
AS_OF = HOUR + timedelta(hours=2)
WINDOW = Window(start=HOUR, end=HOUR)
SCOPE = {"country": "DE", "platform": "android", "provider": "PayCo"}
ARGS = {"node": "payment_success_rate", "window": WINDOW.model_dump(mode="json"), "segment": SCOPE}


def _draft(fid: str) -> ClaimDraft:
    return ClaimDraft(
        kind="observed",
        subject="payment_success_rate",
        segment=SCOPE,
        window=WINDOW,
        fact_ids=[fid],
        text="Observed payment success in the affected slice",
    )


def test_catalogue_uses_executable_c6_handlers(store: EvidenceStore) -> None:
    assert {spec.name for spec in store.specs("investigate")} == {
        "get_series",
        "check_freshness",
        "check_identities",
        "decompose_formula",
        "mix_rate_split",
        "segment_search",
        "list_events",
        "holdout_check",
        "placebo_test",
        "counterfactual_impact",
    }


def test_receipted_ratio_and_signed_change(store: EvidenceStore, ctx: RunContext) -> None:
    observation = store.dispatch(ctx, "get_series", ARGS)
    assert observation.availability == "ok"
    observed, expected, change = observation.fact_handles
    assert (observed.value, expected.value) == (0.6, 0.9)
    claim = store.verify(ctx, _draft(observed.id))
    assert isinstance(claim, VerifiedClaim)
    assert claim.value == 0.6 and claim.unit == "share"
    assert "Observed payment_success_rate" in claim.display
    changed = store.verify(ctx, _draft(change.id).model_copy(update={"kind": "change"}))
    assert isinstance(changed, VerifiedClaim)
    assert changed.value == pytest.approx(-100 / 3)
    assert changed.unit == "pct" and "-33.33%" in changed.display

    (ref,) = claim.receipts
    receipt = store.inspect_receipt(ctx, ref)
    assert receipt is not None and receipt.as_of == AS_OF
    assert store.rerun_receipt(ctx, ref) == (receipt.result_hash, True)
    assert store.receipt_rows(ctx, ref, limit=1) is not None
    assert store.inspect_receipt(ctx.model_copy(update={"through_seq": 3}), ref) is None
    assert store.inspect_receipt(ctx.model_copy(update={"world_revision": "action-a"}), ref) is None
    assert store.inspect_receipt(ctx, ref.model_copy(update={"run_id": "a-different-run"})) is None
    assert store.context_for(ctx.stream, ref, through_seq=ctx.through_seq, as_of=AS_OF) == ctx
    assert store.context_for(ctx.stream, ref, through_seq=ctx.through_seq - 1, as_of=AS_OF) is None


def test_claim_rejects_wrong_metric_unit_time_scope_and_missing_evidence(store: EvidenceStore, ctx: RunContext) -> None:
    observation = store.dispatch(ctx, "get_series", ARGS)
    draft = _draft(observation.fact_handles[0].id)
    for changes, reason in [
        ({"subject": "payment_attempts"}, "wrong_subject"),
        ({"segment": {**SCOPE, "country": "FR"}}, "wrong_subject"),
        ({"kind": "impact"}, "wrong_unit"),
        ({"window": Window(start=HOUR - timedelta(hours=1), end=HOUR)}, "stale"),
        ({"fact_ids": []}, "missing_check"),
        ({"text": "Success was 0.6"}, "unbacked_number"),
    ]:
        rejected = store.verify(ctx, draft.model_copy(update=changes))
        assert isinstance(rejected, Rejection) and rejected.reason == reason
    with pytest.raises(ValidationError):
        ClaimDraft.model_validate({**draft.model_dump(), "unit": "eur"})


def test_swapped_receipt_with_equal_values_fails(
    store: EvidenceStore, ctx: RunContext, runner: Runner, graph: Graph
) -> None:
    first = store.dispatch(ctx, "get_series", ARGS)
    other = ctx.model_copy(update={"run_id": "run_0002"})
    store.bind(other, graph=graph, runner=runner, latest_hour=HOUR)
    second = store.dispatch(other, "get_series", ARGS)
    (first_ref,), (second_ref,) = first.receipt_refs, second.receipt_refs
    assert first.fact_handles[0].value == second.fact_handles[0].value
    assert store.inspect_receipt(ctx, second_ref) is None
    assert isinstance(store.verify(ctx, _draft(second.fact_handles[0].id)), Rejection)

    runner.receipts[first_ref.receipt_id] = runner.receipts[second_ref.receipt_id]
    assert isinstance(store.verify(ctx, _draft(first.fact_handles[0].id)), Rejection)


def test_receipt_swap_is_caught_even_without_hash_or_row_count_difference(
    store: EvidenceStore, ctx: RunContext, runner: Runner
) -> None:
    observation = store.dispatch(ctx, "get_series", ARGS)
    (ref,) = observation.receipt_refs
    receipt = runner.receipts[ref.receipt_id]
    runner.receipts[ref.receipt_id] = receipt.model_copy(update={"sql": receipt.sql + " /* replaced */"})
    assert isinstance(store.verify(ctx, _draft(observation.fact_handles[0].id)), Rejection)
    assert store.rerun_receipt(ctx, ref) == (receipt.result_hash, False)


def test_reverification_rejects_changed_rows_under_the_original_sql(
    store: EvidenceStore, ctx: RunContext, runner: Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    observation = store.dispatch(ctx, "get_series", ARGS)
    fetch = runner.fetch

    def changed(sql: str, as_of: datetime) -> list[dict]:
        rows = fetch(sql, as_of)
        rows[0]["num"] += 1
        return rows

    monkeypatch.setattr(runner, "fetch", changed)
    assert isinstance(store.verify(ctx, _draft(observation.fact_handles[0].id)), Rejection)


def test_unavailable_and_rejected_calls_mint_no_facts(store: EvidenceStore, ctx: RunContext, runner: Runner) -> None:
    total_before = runner.query_count
    for tool, args in [
        ("lag_test", {"x": "orders", "y": "ad_spend"}),
        ("get_series", {**ARGS, "node": "raw_payments_hourly"}),
        ("get_series", {**ARGS, "window": {"start": HOUR, "end": AS_OF}}),
        ("get_series", {**ARGS, "segment": {"provider": "unavailable"}}),
    ]:
        refused = store.dispatch(ctx, tool, args)
        assert refused.availability == "rejected" and not refused.fact_handles
    assert runner.query_count == total_before

    no_formula = store.dispatch(ctx, "decompose_formula", {**ARGS, "node": "sessions", "segment": {}})
    assert no_formula.availability == "unavailable"
    assert not no_formula.fact_handles
    no_rows = store.dispatch(ctx, "get_series", {**ARGS, "segment": {"country": "ES"}})
    assert no_rows.availability == "unavailable" and not no_rows.fact_handles
    no_volume = store.dispatch(ctx, "counterfactual_impact", {**ARGS, "segment": {"country": "ES"}})
    assert no_volume.availability == "unavailable" and not no_volume.fact_handles


def test_holdout_uses_the_recorded_event_with_its_exact_scope(store: EvidenceStore, ctx: RunContext) -> None:
    listed = store.dispatch(
        ctx, "list_events", {"start": HOUR - timedelta(hours=1), "end": HOUR, "logs": ["log_deploys"]}
    )
    (event,) = listed.data["events"]
    invalid = store.dispatch(ctx, "holdout_check", {**ARGS, "event": {**event, "scope": {}}})
    assert invalid.availability == "rejected" and not invalid.fact_handles
    holdout = store.dispatch(ctx, "holdout_check", {**ARGS, "event": event})
    assert holdout.availability == "ok" and holdout.outcome == "refuted"
    assert "where" not in holdout.data["holdout"]
    rejected_event = next(handle for handle in holdout.fact_handles if "failed its" in handle.label)
    claim = store.verify(
        ctx,
        _draft(rejected_event.id).model_copy(
            update={
                "kind": "ruled_out",
                "subject": "android_release",
            }
        ),
    )
    assert isinstance(claim, VerifiedClaim) and len(claim.receipts) == 3
    assert listed.receipt_refs[0] in claim.receipts


def test_market_extension_binds_the_visible_anomaly(
    store: EvidenceStore, ctx: RunContext, runner: Runner, graph: Graph
) -> None:
    market_ctx = ctx.model_copy(update={"run_id": "market", "anomaly_id": "an_0001"})
    anomaly = Anomaly(
        id="an_0001",
        node="sessions",
        segment={"country": "DE"},
        direction="down",
        hour=HOUR,
        detected_at=AS_OF,
        onset=HOUR,
        observed=70,
        expected=100,
        band=(94, 106),
        z=-10,
        rule="z_gt_open",
    )
    store.bind(market_ctx, graph=graph, runner=runner, latest_hour=HOUR, anomaly=anomaly)
    unknown = store.dispatch(market_ctx, "check_control_group", {"anomaly_id": "an_0002"})
    assert unknown.availability == "unavailable"
    market = store.dispatch(market_ctx, "check_control_group", {"anomaly_id": anomaly.id})
    assert market.outcome == "market"
    fact = next(handle for handle in market.fact_handles if "residual change" in handle.label)
    claim = store.verify(
        market_ctx,
        ClaimDraft(
            kind="change",
            subject="sessions",
            segment={"country": "DE"},
            window=WINDOW,
            fact_ids=[fact.id],
            text="Residual against the market",
        ),
    )
    assert isinstance(claim, VerifiedClaim) and claim.value == pytest.approx(0)
    assert store.claims_at(ctx.stream, ctx.through_seq - 1, AS_OF) == []
    assert store.claims_at(ctx.stream, ctx.through_seq, AS_OF) == [(market_ctx, claim)]


def test_counterfactual_extension_attaches_both_world_proofs(
    store: EvidenceStore, ctx: RunContext, runner: Runner, graph: Graph, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording = load_recording(FIXTURES / "s4")
    incident = recording.incidents[0].incident
    root = incident.findings.root
    assert root is not None
    reference = next(receipt for receipt in recording.receipts if receipt.id == root.change_pct.receipt)
    runner.receipts[reference.id] = reference
    when = incident.findings.as_of
    asking = ctx.model_copy(update={"run_id": "asking", "kind": "ask", "as_of": when})
    config = WorldConfig(seed=1)
    plan = make_plan(incident, config, when)
    result = CounterfactualResult(
        factual_series=[],
        counterfactual_series=[],
        explained_share=0.75,
        gap=Gap(factual=4, counterfactual=1, removed=3),
        receipt=ReplayReceipt(
            plan=plan,
            factual=QueryProof(sql="SELECT 4", result_hash="sha256:factual", rows=1),
            counterfactual=QueryProof(sql="SELECT 1", result_hash="sha256:counterfactual", rows=1),
        ),
    )
    calls = []

    def replay(observed, **kwargs):
        assert observed == incident
        assert kwargs == {"config": config, "as_of": when, "reference": reference}
        calls.append(observed.id)
        return result

    monkeypatch.setattr("argus.evidence.store.counterfactual", replay)
    store.bind(asking, graph=graph, runner=runner, latest_hour=plan.window.end, incidents=[incident], config=config)
    observation = store.dispatch(asking, "counterfactual", {"incident_id": incident.id})
    assert observation.availability == "ok" and len(observation.receipt_refs) == 2
    assert "config" not in observation.data
    assumption = ClaimDraft(
        kind="share",
        subject=plan.metric,
        segment=plan.segment,
        window=Window(start=plan.onset, end=plan.window.end),
        fact_ids=[observation.fact_handles[0].id],
        text="Share of the deviation explained by the replay",
    )
    verified = store.verify(asking, assumption)
    assert isinstance(verified, VerifiedClaim) and verified.value == 0.75
    assert verified.receipts == observation.receipt_refs and len(calls) == 2
    expected_hashes = ["sha256:factual", "sha256:counterfactual"]
    for ref, expected_hash in zip(verified.receipts, expected_hashes, strict=True):
        receipt = store.inspect_receipt(asking, ref)
        assert receipt is not None and receipt.result_hash == expected_hash
        assert receipt.as_of == plan.as_of
