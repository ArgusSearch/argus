"""One example per frozen type (types.py), from the recorded S1 seed-1 run. Lanes build fixtures from these;
docs/ext/agent.md prints them and tests/agent_runtime validates them."""

from __future__ import annotations

from datetime import datetime

from argus.agent.types import (
    BOARD_VERSION,
    ActivityRecord,
    Board,
    CaseNote,
    CauseChain,
    ChainLink,
    Challenge,
    CheckRef,
    ClaimDraft,
    CostLine,
    CostView,
    CriticView,
    Decision,
    DeclaredHypothesis,
    Discarded,
    EffectResult,
    FactHandle,
    GateResult,
    HypothesisCard,
    HypothesisMove,
    LlmRequest,
    LlmResponse,
    Observation,
    Precedent,
    ProposalView,
    ReceiptLink,
    Rejection,
    RunContext,
    RunSummary,
    SecondOpinion,
    SqlJudgement,
    StepGroup,
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

CHECK = CheckRef(
    seq=9,
    call_id="run_0001:3",
    step=10,
    tool="holdout_check",
    by="detective",
    status="validated",
    outcome="consistent",
    summary="control normal, the change sits where the event applies: -0.2% (z -0.4) vs -36.2% inside [r241]",
    receipts=[link("r241")],
)

CARD = HypothesisCard(
    id="H2",
    statement="event: PayCo: elevated decline rates for Android SDK payments in Germany",
    kind="event",
    subject="ps_payco_degraded",
    source="host",
    status="supported",
    reason="holdout consistent: the change sits where the event applies",
    decisive_check="holdout_check",
    checks=[CHECK],
)

GROUP = StepGroup(
    id="run_0001:g2",
    title="Checks",
    phase="checks",
    role="detective",
    first_seq=2,
    last_seq=12,
    status="done",
    steps=11,
    tool_calls=4,
    usd=0.0291,
    summary="4 checks: list_events, holdout_check, holdout_check, placebo_test",
)

DISCARDED = Discarded(
    kind="ruled_out",
    text="android-app 8.3.0 rolled out to 100% of Android users in all countries: holdout normal [r240]",
    seq=7,
    receipts=[link("r240")],
)

LINK = ChainLink(
    kind="formula",
    source="payment_success_rate",
    target="orders",
    label="payment success rate carries 103% of the change of orders",
    share=1.0312,
    status="tested",
    receipts=[link("r246")],
)

CHAIN = CauseChain(
    incident_id="INC-0001",
    links=[
        ChainLink(
            kind="event",
            source="ps_payco_degraded",
            target="payment_success_rate",
            label="PayCo: elevated decline rates for Android SDK payments in Germany",
            share=None,
            status="tested",
            receipts=[link("r241")],
        ),
        LINK,
    ],
    text="PayCo degraded -> payment success rate DE / android / PayCo -> orders -> EUR lost",
)

COST_LINE = CostLine(
    phase="detective", model="claude-sonnet-5-5", llm_calls=4, input_tokens=22910, output_tokens=1211, usd=0.039186
)

COST = CostView(
    usd=0.039186, cap_usd=0.5, llm_calls=4, tool_calls=4, cap_tool_calls=12, replayed=True, lines=[COST_LINE]
)

CRITIC = CriticView(
    result="upheld",
    model="claude-opus-5-5",
    attempts=2,
    reason="2 attempts to falsify, none succeeded",
    checks=[CHECK.model_copy(update={"seq": 21, "call_id": "run_0001:c1", "step": None, "by": "critic"})],
)

PRECEDENT = Precedent(
    case_id="INC-0001",
    sim_ts=datetime(2026, 11, 20, 2),
    cause="deploy:ad-pacer",
    playbook_id="rollback_pacer",
    decision="deny",
    effect=None,
    policy="suppress_denied",
    note="Not proposing the pacer rollback again: the operator denied it at 2026-11-20 02:00.",
)

SECOND_OPINION = SecondOpinion(method="STL residual (statsmodels)", z=-6.2, agrees=True, receipts=[link("r225")])

BOARD = Board(
    version=BOARD_VERSION,
    agent_run="run_0001",
    incident_id="INC-0001",
    anomaly_id="an_0001",
    through_seq=17,
    state="done",
    profile="v1",
    hypotheses=[CARD],
    counts={"open": 0, "supported": 1, "ruled_out": 0, "inconclusive": 0, "not_tested": 0},
    groups=[GROUP],
    discarded=[DISCARDED],
    chain=CHAIN,
    critic=None,
    precedents=[],
    second_opinion=None,
    cost=COST,
)

DECLARED = DeclaredHypothesis(
    id="H1",
    statement="The android release broke payments everywhere on android",
    kind="event",
    event_ref="dep_android-app_8.3.0",
    decisive_check="holdout_check",
    why_cheapest="one holdout outside the segment refutes it",
)

MOVE = HypothesisMove(id="H1", status="ruled_out", reason="holdout normal outside the segment", call_id="run_0001:2")

CHALLENGE = Challenge(
    verdict="upheld",
    downgrade=False,
    reason="no rule fired: the holdout and the placebo of the counter-check agree with the cause",
    checks=[{"tool": "placebo_test", "outcome": "unusual", "receipts": ["r250"]}],
)

SQL_JUDGEMENT = SqlJudgement(
    accepted=True,
    rule=None,
    outcome="holds",
    summary="PayCo below the other providers in DE / android: 0.61 vs 0.95 [r251]",
    rows=[{"provider": "PayCo", "rate": 0.607}, {"provider": "WalletGo", "rate": 0.951}],
    receipt_id="r251",
)

CASE_NOTE = CaseNote(
    case_id="INC-0001",
    sim_ts=datetime(2026, 11, 20, 2),
    fingerprint="3f1c0b2a9e7d",
    root_node="pacing_ratio",
    segment_dims=[],
    verdict="SUPPORTED_CAUSE",
    cause_kind="deploy:ad-pacer",
    cause_ref="dep_ad-pacer_1.7.0",
    deciding_checks=["holdout_check", "placebo_test"],
    playbook_id="rollback_pacer",
    decision="deny",
    effect=None,
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
    "CheckRef": CHECK,
    "HypothesisCard": CARD,
    "StepGroup": GROUP,
    "Discarded": DISCARDED,
    "ChainLink": LINK,
    "CauseChain": CHAIN,
    "CostLine": COST_LINE,
    "CostView": COST,
    "CriticView": CRITIC,
    "Precedent": PRECEDENT,
    "SecondOpinion": SECOND_OPINION,
    "Board": BOARD,
    "DeclaredHypothesis": DECLARED,
    "HypothesisMove": MOVE,
    "Challenge": CHALLENGE,
    "SqlJudgement": SQL_JUDGEMENT,
    "CaseNote": CASE_NOTE,
}
