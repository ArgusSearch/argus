"""One example per frozen type (types.py), from the recorded S1 seed-1 run. Lanes build fixtures from these;
docs/ext/agent.md prints them and tests/agent_runtime validates them."""

from __future__ import annotations

from datetime import datetime

from argus.agent.types import (
    ActivityRecord,
    ClaimDraft,
    Decision,
    EffectResult,
    FactHandle,
    GateResult,
    LlmRequest,
    LlmResponse,
    Observation,
    ProposalView,
    ReceiptLink,
    Rejection,
    RunContext,
    RunSummary,
    SuccessRule,
    ToolSpec,
    UsageRecord,
    VerifiedClaim,
)
from argus.contracts.findings import Window

AS_OF = datetime(2026, 11, 21, 20)
HOUR = datetime(2026, 11, 21, 18)
WINDOW = Window(start=HOUR, end=HOUR)
SEGMENT = {"country": "DE", "platform": "android", "provider": "PayCo"}


def link(receipt: str) -> ReceiptLink:
    return ReceiptLink(run_id="run_0001", world_revision="factual", receipt_id=receipt)


CONTEXT = RunContext(
    run_id="run_0001",
    stream="9f3c2a1b",
    through_seq=125,
    world_revision="factual",
    as_of=AS_OF,
    anomaly_id="an_0001",
    kind="investigate",
    mode="replay",
)

TOOL = ToolSpec(
    name="holdout_check",
    description="Is the event's scope outside the anomalous segment normal? Runs SQL with a receipt.",
    input_schema={"type": "object", "properties": {"event": {"type": "object"}, "node": {"type": "string"}}},
    kinds=["investigate", "ask"],
)

FACT = FactHandle(
    id="f:run_0001:run_0001:2:1",
    label="payment_success_rate DE/android/PayCo 18:00, observed",
    value=0.607383,
    unit="ratio",
    receipts=[link("a2")],
)

OBSERVATION = Observation(
    call_id="run_0001:2",
    tool="holdout_check",
    args={
        "node": "payment_success_rate",
        "segment": SEGMENT,
        "window": {"start": HOUR.isoformat(), "end": HOUR.isoformat()},
    },
    hypothesis="The Android release 8.3.0 caused the drop",
    prediction="Android outside DE/PayCo also drops",
    expect="consistent",
    outcome="refuted",
    summary="holdout normal: -0.1% (z -0.4) outside the segment vs -34.3% inside",
    data={"rel_change": -0.001, "z": -0.4, "result": "refuted"},
    fact_handles=[FACT],
    receipt_refs=[link("a7")],
)

DRAFT = ClaimDraft(
    kind="observed",
    subject="payment_success_rate",
    segment=SEGMENT,
    window=WINDOW,
    fact_ids=[FACT.id],
    text="payment success in the segment",
)

CLAIM = VerifiedClaim(
    claim_id="c:run_0001:1",
    kind="observed",
    subject="payment_success_rate",
    segment=SEGMENT,
    window=WINDOW,
    as_of=AS_OF,
    world_revision="factual",
    value=0.607383,
    unit="ratio",
    display="Payment success in DE / android / PayCo was 0.607 at 18:00 [a2].",
    receipts=[link("a2")],
)

REJECTION = Rejection(
    reason="missing_check", detail="no placebo_test for the root segment", upgrade="placebo_test on DE/android/PayCo"
)

PROPOSAL = ProposalView(
    id="act_0001",
    digest="sha256:0f1e...",
    state="AWAIT_OPERATOR",
    run_id="run_0001",
    incident_ref="INC-0001",
    playbook_id="rollback_pacer",
    action="Roll the ad pacer back from 1.7.0 for the DE and FR budget lines from 2026-11-21 00:00.",
    scope={"country": ["DE", "FR"]},
    effective_at=datetime(2026, 11, 21, 0),
    expires_at=datetime(2026, 11, 21, 2),
    success_rule=SuccessRule(
        node="pacing_ratio",
        scope={"country": ["DE", "FR"]},
        rule="|ratio - 1| <= 0.15 and gap at most half the untreated twin's, 3 complete hours",
        hours=3,
    ),
    evidence_refs=[link("r184")],
    decision=None,
    effect=None,
)

DECISION = Decision(decision="approve", principal="operator", at=datetime(2026, 11, 20, 3))

EFFECT = EffectResult(
    state="VERIFIED",
    checked_at=datetime(2026, 11, 21, 5),
    summary="DE/FR pacing back in band for 3 hours",
    claims=[],
    receipt_refs=[link("a31")],
)

ACTIVITY = ActivityRecord(
    seq=7,
    run_id="run_0001",
    sim_ts=AS_OF,
    kind="tool_result",
    stage="OBSERVE",
    actor="host",
    text="holdout normal: -0.1% (z -0.4) outside the segment vs -34.3% inside [a7]",
    anomaly_id="an_0001",
    incident_id="INC-0001",
    tool="holdout_check",
    observation=OBSERVATION,
    receipt_links=[link("a7")],
)

USAGE = UsageRecord(
    run_id="run_0001",
    call_index=1,
    model="claude-sonnet-5-5",
    request_id="req_redacted",
    input_tokens=5329,
    output_tokens=412,
    cache_read_tokens=12388,
    cache_write_tokens=0,
    usd=0.01065,
    tariff="anthropic-2026-11",
    stop_reason="tool_use",
    wall_ms=3120,
)

RUN = RunSummary(
    run_id="run_0001",
    kind="investigate",
    mode="replay",
    sim_ts=AS_OF,
    anomaly_id="an_0001",
    incident_id="INC-0001",
    status="done",
    llm_calls=6,
    tool_calls=9,
    input_tokens=48881,
    output_tokens=4833,
    usd=0.1096,
    gate=GateResult(claimed="SUPPORTED_CAUSE", admitted="SUPPORTED_CAUSE", reasons=[]),
)

REQUEST = LlmRequest(
    model="claude-sonnet-5-5",
    system="You are Argus Agent ...",
    tools=[TOOL.model_dump(exclude={"kinds"})],
    messages=[{"role": "user", "content": "Case INC-0001 ..."}],
    max_tokens=4000,
    key="investigate:an_0001:1",
)

RESPONSE = LlmResponse(
    model="claude-sonnet-5-5",
    content=[
        {"type": "text", "text": "The release went to every country; if it caused this, Android elsewhere drops too."},
        {
            "type": "tool_use",
            "id": "toolu_redacted",
            "name": "holdout_check",
            "input": {"node": "payment_success_rate"},
        },
    ],
    stop_reason="tool_use",
    usage={
        "input_tokens": 5329,
        "output_tokens": 412,
        "cache_read_input_tokens": 12388,
        "cache_creation_input_tokens": 0,
    },
    request_id="req_redacted",
)

EXAMPLES = {
    "RunContext": CONTEXT,
    "ReceiptLink": link("a7"),
    "ToolSpec": TOOL,
    "FactHandle": FACT,
    "Observation": OBSERVATION,
    "ClaimDraft": DRAFT,
    "VerifiedClaim": CLAIM,
    "Rejection": REJECTION,
    "ProposalView": PROPOSAL,
    "Decision": DECISION,
    "EffectResult": EFFECT,
    "ActivityRecord": ACTIVITY,
    "UsageRecord": USAGE,
    "RunSummary": RUN,
    "LlmRequest": REQUEST,
    "LlmResponse": RESPONSE,
}
