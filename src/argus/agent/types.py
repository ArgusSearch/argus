"""FROZEN INTERFACE of the Argus agent (lanes A-F code against this file; docs/ext/agent.md).

Changes only by request to lane A. Every model is strict (unknown fields are an error) and JSON-serialisable,
so the same objects travel through the API, the activity log, recordings and tests.

Ownership of the types (implementations live with their owner):

| types                                                        | owner | implementation             |
|--------------------------------------------------------------|-------|----------------------------|
| RunContext, ReceiptLink, ActivityRecord, RunSummary, Usage*, | A     | src/argus/agent/           |
| LlmRequest, LlmResponse, LlmClient, ActivitySink, AgentMode  |       |                            |
| ToolSpec, Observation, FactHandle, ClaimDraft,               | B     | src/argus/evidence/        |
| VerifiedClaim, Rejection, Dispatcher, Verifier               |       |                            |
| ProposalView, SuccessRule, EffectResult, Decision,           | C     | src/argus/remediation/     |
| ProposalService                                              |       |                            |

Rules every lane relies on:

* numbers: a figure shown to a human is a `VerifiedClaim` (or a `FactHandle` value) bound to receipts of the
  run that produced it; prose numbers are re-checked against the run's facts (`argus.agent.numbers`);
* evidence references always carry the run and the world revision (`ReceiptLink`);
* the model never sees credentials, never calls an approval route and never supplies actuator parameters;
* times are naive UTC, simulated (`sim_ts`, `as_of`), never wall clock, except `UsageRecord.wall_ms`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.findings import Segment, Window
from argus.investigate.ledger import LedgerEntry

INTERFACE_VERSION = "agent-types/1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


AgentMode = Literal["live", "record", "replay", "off"]
"""live: model calls; record: live plus a recording; replay: no provider is ever constructed; off: Stage 2 only."""

RunKind = Literal["investigate", "ask", "morning", "verify_effect"]


# ---------------------------------------------------------------------------------------------- A: context


class RunContext(_Strict):
    """Pinned for one agent run. Every tool call, claim and proposal is scoped by it."""

    run_id: str = Field(description="'run_0001', ... unique within a stream")
    stream: str = Field(description="C5 stream id (EventHub.stream) the run belongs to")
    through_seq: int = Field(description="last C5 seq visible to the run; nothing later may be read")
    world_revision: str = Field(description="identity of the world the run reads: 'factual' or an action branch id")
    as_of: datetime = Field(description="pinned simulated clock of every query")
    anomaly_id: str | None = None
    incident_id: str | None = None
    kind: RunKind = "investigate"
    mode: AgentMode = "live"


class ReceiptLink(_Strict):
    """A qualified receipt: ids like 'r12' or 'a3' are only unique within one run and world revision."""

    run_id: str
    world_revision: str
    receipt_id: str

    def key(self) -> str:
        return f"{self.run_id}/{self.world_revision}/{self.receipt_id}"


# ---------------------------------------------------------------------------------------------- B: tools and evidence


class ToolSpec(_Strict):
    """A tool as the provider sees it (Anthropic `tools` entry; also the MCP shape)."""

    name: str
    description: str
    input_schema: dict[str, Any]
    kinds: list[RunKind] = Field(description="run kinds whose tool list includes it")


Availability = Literal["ok", "unavailable", "rejected", "error"]
"""ok: ran; unavailable: not applicable here (no formula, no control); rejected: invalid arguments or a
policy refusal (unknown table, window after the latest complete hour); error: the check failed to run."""


class FactHandle(_Strict):
    """One number an observation produced, addressable by the model instead of retyping it."""

    id: str = Field(description="'f:<run_id>:<call_id>:<n>', minted by the dispatcher")
    label: str = Field(description="what the number is, e.g. 'payment_success_rate DE/android/PayCo 18:00'")
    value: float
    unit: str = Field(description="count | eur | share | pct | ratio | z | hours")
    receipts: list[ReceiptLink]


class Observation(_Strict):
    """The result of one dispatched tool call, as the loop, the activity log and the verifier see it."""

    call_id: str = Field(description="'<run_id>:<n>' in call order")
    tool: str
    args: dict[str, Any] = Field(description="the validated arguments that ran (naive UTC)")
    hypothesis: str | None = None
    prediction: str | None = Field(default=None, description="journaled before dispatch")
    expect: str | None = Field(
        default=None, description="outcome that would support the hypothesis (ledger vocabulary)"
    )
    outcome: str | None = Field(default=None, description="ledger outcome label of the result, None when in between")
    ledger: LedgerEntry | None = Field(default=None, description="deterministic verdict when `expect` was given")
    summary: str = Field(description="one line for the model and the activity log")
    data: dict[str, Any] = Field(default_factory=dict, description="bounded structured result shown to the model")
    fact_handles: list[FactHandle] = Field(default_factory=list)
    receipt_refs: list[ReceiptLink] = Field(default_factory=list)
    availability: Availability = "ok"


ClaimKind = Literal["observed", "change", "share", "impact", "cause", "ruled_out", "recovered", "count"]


class ClaimDraft(_Strict):
    """What the model submits instead of typing a number: a statement bound to fact handles."""

    kind: ClaimKind
    subject: str = Field(description="graph node id, event ref or action id the claim is about")
    segment: Segment = Field(default_factory=dict)
    window: Window | None = None
    fact_ids: list[str] = Field(description="FactHandle ids that carry the claim")
    text: str = Field(description="wording without numbers; the host renders the figures")


class VerifiedClaim(_Strict):
    claim_id: str
    kind: ClaimKind
    subject: str
    segment: Segment = Field(default_factory=dict)
    window: Window | None = None
    as_of: datetime
    world_revision: str
    value: float | None = None
    unit: str | None = None
    display: str = Field(description="the sentence as shown, figures rendered by the host with receipt tags")
    receipts: list[ReceiptLink]


class Rejection(_Strict):
    """Why a draft (claim, verdict, report, proposal) was not admitted. Goes back to the model once."""

    reason: Literal[
        "unbacked_number", "unknown_fact", "wrong_subject", "wrong_unit", "stale", "missing_check", "policy", "invalid"
    ]
    detail: str
    upgrade: str | None = Field(default=None, description="the check that would admit it")


# ---------------------------------------------------------------------------------------------- C: proposals and effect

ProposalState = Literal[
    "AWAIT_OPERATOR",
    "DENIED",
    "EXPIRED",
    "APPLYING",
    "APPLIED",
    "VERIFYING",
    "VERIFIED",
    "NO_EFFECT",
    "INCONCLUSIVE",
]


class SuccessRule(_Strict):
    """How the effect of an action is judged, fixed before approval."""

    node: str = Field(description="e.g. pacing_ratio")
    scope: dict[str, list[str]] = Field(description="treated segments, e.g. {'country': ['DE', 'FR']}")
    rule: str = Field(description="human-readable rule, e.g. '|ratio - 1| <= 0.15 for 3 complete hours'")
    hours: int
    comparator: Literal["expectation", "untreated_twin"] = "untreated_twin"


class EffectResult(_Strict):
    state: Literal["VERIFIED", "NO_EFFECT", "INCONCLUSIVE"]
    checked_at: datetime
    summary: str
    claims: list[VerifiedClaim] = Field(default_factory=list)
    receipt_refs: list[ReceiptLink] = Field(default_factory=list)


class Decision(_Strict):
    decision: Literal["approve", "deny"]
    principal: str = Field(description="authenticated operator, never the model")
    at: datetime = Field(description="simulated time of the decision")


class ProposalView(_Strict):
    """An immutable proposal plus its current state. The digest covers everything an approval approves."""

    id: str = Field(description="'act_0001', ...")
    digest: str = Field(
        description="sha256 over run, world revision, incident fingerprint, evidence, action, scope, times"
    )
    state: ProposalState
    run_id: str
    incident_ref: str = Field(description="incident id")
    playbook_id: str = Field(description="e.g. 'rollback_pacer'")
    action: str = Field(description="one sentence, rendered by the host from typed parameters")
    scope: dict[str, list[str]]
    effective_at: datetime
    expires_at: datetime
    success_rule: SuccessRule
    evidence_refs: list[ReceiptLink]
    decision: Decision | None = None
    effect: EffectResult | None = None


# ---------------------------------------------------------------------------------------------- A: activity and runs

ActivityKind = Literal[
    "run_started",
    "thought",  # the visible sentence before a tool call; hidden reasoning is never logged
    "tool_call",  # journaled before dispatch: tool, args, hypothesis, prediction
    "tool_result",  # the Observation
    "gate",  # the verdict gate's decision (claimed, admitted, reasons)
    "report",  # a report that passed the number check
    "rejected",  # a draft the number check or the gate sent back
    "action_proposed",
    "action_decided",
    "action_applied",
    "effect_checked",
    "budget",
    "fallback",  # Stage 2 took over, with the reason
    "chat_question",
    "chat_answer",
    "watch",  # a quiet hour: no model call
    "run_finished",
]

Stage = Literal["WATCH", "TRIAGE", "PLAN", "ACT", "OBSERVE", "VERIFY", "REPORT", "PROPOSE", "AWAIT_OPERATOR", "ASK"]


class ActivityRecord(_Strict):
    """One line of the agent activity log; also the payload of `GET /agent/activity`."""

    seq: int = Field(description="strictly increasing within a stream")
    run_id: str | None = Field(description="None for watch lines")
    sim_ts: datetime
    kind: ActivityKind
    stage: Stage
    actor: Literal["model", "host", "operator"]
    text: str = Field(default="", description="numbers only as the host rendered them (with receipt tags)")
    anomaly_id: str | None = None
    incident_id: str | None = None
    action_id: str | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    observation: Observation | None = None
    receipt_links: list[ReceiptLink] = Field(default_factory=list)
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    usd: float | None = None
    gate_action: str | None = Field(default=None, description="replay: action id whose approval releases this record")


class UsageRecord(_Strict):
    """One provider call, as billed (cache tiers included)."""

    run_id: str
    call_index: int
    provider: Literal["anthropic"] = "anthropic"
    model: str = Field(description="model id the response reported")
    request_id: str | None = None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    usd: float | None = Field(description="None when the tariff is unknown: trips the run's budget, never guessed")
    tariff: str = Field(description="tariff version used for usd")
    stop_reason: str
    wall_ms: int


class GateResult(_Strict):
    claimed: str = Field(description="C4 verdict the model claimed")
    admitted: str = Field(description="C4 verdict the deterministic gate admitted")
    reasons: list[str] = Field(default_factory=list)


class RunSummary(_Strict):
    run_id: str
    kind: RunKind
    mode: AgentMode
    sim_ts: datetime
    anomaly_id: str | None = None
    incident_id: str | None = None
    status: Literal["running", "done", "budget", "failed", "fallback"]
    stop_reason: str | None = None
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    gate: GateResult | None = None
    fallback: str | None = Field(default=None, description="why Stage 2 took over ('baseline_fallback: ...')")


# ---------------------------------------------------------------------------------------------- A: provider


class LlmRequest(_Strict):
    model: str
    system: str
    tools: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    max_tokens: int
    key: str = Field(description="recording key '<kind>:<subject>:<round>', e.g. 'investigate:an_0001:3'")


class LlmResponse(_Strict):
    model: str
    content: list[dict[str, Any]] = Field(description="Anthropic content blocks (text, thinking, tool_use)")
    stop_reason: str
    usage: dict[str, int] = Field(
        description="input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens"
    )
    request_id: str | None = None


# ---------------------------------------------------------------------------------------------- protocols


class LlmClient(Protocol):
    """Live (Anthropic), recording or replaying. A replaying client never opens a socket."""

    def create(self, request: LlmRequest) -> LlmResponse: ...


class ActivitySink(Protocol):
    def emit(self, record: ActivityRecord) -> None: ...


class Dispatcher(Protocol):
    """Lane B. The only way the agent reads data. Validates, runs, binds facts; never raises on bad args."""

    def specs(self, kind: RunKind) -> list[ToolSpec]: ...

    def dispatch(self, ctx: RunContext, name: str, args: dict[str, Any]) -> Observation: ...


class Verifier(Protocol):
    """Lane B. Re-derives a claim's value from its receipts; anything it cannot re-derive is rejected."""

    def verify(self, ctx: RunContext, draft: ClaimDraft) -> VerifiedClaim | Rejection: ...


class ProposalService(Protocol):
    """Lane C. Proposals are derived by the host from the admitted incident and evidence, never from prose."""

    def propose(
        self, ctx: RunContext, incident_id: str, playbook_id: str, evidence: list[ReceiptLink]
    ) -> ProposalView | Rejection: ...

    def get(self, proposal_id: str) -> ProposalView | None: ...

    def decide(self, proposal_id: str, digest: str, decision: Decision, idempotency_key: str) -> ProposalView: ...
