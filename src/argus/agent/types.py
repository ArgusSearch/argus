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
| Board and its parts (HypothesisCard, CheckRef, StepGroup,    | Q1    | src/argus/agent/board.py,  |
| Discarded, CauseChain, ChainLink, CostView, CostLine,        |       | src/argus/agent/chain.py   |
| CriticView, Precedent, SecondOpinion), DeclaredHypothesis,   |       |                            |
| HypothesisMove                                               |       |                            |
| Challenge, Critic                                            | Q2    | src/argus/skeptic/critic.py|
| SqlJudgement, SqlValidator, SqlCheckRunner                   | Q3    | src/argus/evidence/sqlgate |
| CaseNote, CaseMemory, ProposalPolicy                         | Q3    | src/argus/agent/memory.py  |

Rules every lane relies on:

* numbers: a figure shown to a human is a `VerifiedClaim` (or a `FactHandle` value) bound to receipts of the
  run that produced it; prose numbers are re-checked against the run's facts (`argus.agent.numbers`);
* evidence references always carry the run and the world revision (`ReceiptLink`);
* the model never sees credentials, never calls an approval route and never supplies actuator parameters;
* times are naive UTC, simulated (`sim_ts`, `as_of`), never wall clock, except `UsageRecord.wall_ms`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.findings import Segment, Window
from argus.investigate.ledger import LedgerEntry

INTERFACE_VERSION = "agent-types/1"
BOARD_VERSION: Literal["agent-board/1"] = "agent-board/1"
"""Version of the derived read model (`Board`), independent of the frozen record types above."""

ProfileName = Literal["v1", "v2"]
"""v1: the recorded behaviour, byte-identical forever; v2: the techniques below, each behind one `Feature`."""

Feature = Literal["critic", "sql", "hypotheses", "memory", "second_opinion"]
FEATURES: tuple[Feature, ...] = ("critic", "sql", "hypotheses", "memory", "second_opinion")


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
    # profile v2 only (new values, never new fields: v1 recordings keep their bytes). Readers render unknown kinds
    # as a plain line. The structured payload rides in `args`, see "v2 activity payloads" below.
    "hypothesis",  # declared hypotheses (args: {"declared": [DeclaredHypothesis]}) or a move ({"move": ...})
    "critic",  # the counter-check's outcome (args: Challenge plus "model")
    "memory",  # a precedent from case memory changed or annotated a proposal (args: Precedent)
]

Role = Literal["watcher", "detective", "skeptic", "market", "narrator", "operator", "cartographer"]
"""Who acts in a record, for the avatars: watcher (hourly watch), detective (planning, localising, events),
skeptic (holdouts, placebo, the gate), market (market control), narrator (reports, answers), operator
(human decisions and actions), cartographer (graph and metric placement)."""

Stage = Literal["WATCH", "TRIAGE", "PLAN", "ACT", "OBSERVE", "VERIFY", "REPORT", "PROPOSE", "AWAIT_OPERATOR", "ASK"]


class ActivityRecord(_Strict):
    """One line of the agent activity log; also the payload of `GET /agent/activity`."""

    seq: int = Field(description="strictly increasing within a stream")
    run_id: str | None = Field(description="None for watch lines")
    sim_ts: datetime
    kind: ActivityKind
    stage: Stage
    actor: Literal["model", "host", "operator"]
    role: Role | None = Field(default=None, description="avatar role; the journal derives it when not given")
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


# ---------------------------------------------------------------------------------------------- Q1: derived board
#
# A read model, never recorded: `argus.agent.board.build_board` derives it from activity records and C4 findings
# (pure function, same input -> same JSON). Served by `GET /agent/boards` (docs/ext/agent.md).

HypothesisStatus = Literal["open", "supported", "ruled_out", "inconclusive", "not_tested"]
HYPOTHESIS_STATUSES: tuple[HypothesisStatus, ...] = ("open", "supported", "ruled_out", "inconclusive", "not_tested")
HypothesisKind = Literal["event", "data", "planned", "market", "mix", "recurring", "segment", "other"]
CheckStatus = Literal["validated", "refuted", "inconclusive", "observed", "rejected"]


class CheckRef(_Strict):
    """One check behind a card, a critic verdict or a discarded path."""

    seq: int | None = Field(description="activity seq of the tool_result, None for trail-only steps")
    call_id: str | None = Field(description="'<run_id>:<n>' detective, '<run_id>:c<n>' critic, None for the host")
    step: int | None = Field(description="C4 trail step number, None when the check is not in the trail")
    tool: str
    by: Literal["host", "detective", "critic"]
    status: CheckStatus
    outcome: str | None = Field(description="ledger outcome label (consistent, refuted, unusual, ...)")
    summary: str = Field(description="host-rendered, numbers only with receipt tags")
    receipts: list[ReceiptLink]


class HypothesisCard(_Strict):
    id: str = Field(description="'H1', ... in order of first appearance; stable while the run advances")
    parent: str | None = None
    statement: str = Field(description="no digits")
    kind: HypothesisKind
    subject: str | None = Field(description="event ref or node id")
    source: Literal["host", "model", "critic"]
    status: HypothesisStatus
    reason: str = Field(description="one line: why it has this status")
    decisive_check: str | None = None
    checks: list[CheckRef]


StepPhase = Literal["opening", "hypotheses", "checks", "critic", "verdict", "report", "action", "effect", "ask"]


class StepGroup(_Strict):
    """Consecutive activity records of one phase, for a collapsed run log."""

    id: str = Field(description="'<run_id>:g<n>'")
    title: str = Field(description="'Opening checks', 'Candidates', 'Counter-check', 'Verdict', 'Action', 'Effect'")
    phase: StepPhase
    role: Role
    first_seq: int
    last_seq: int
    status: Literal["running", "done", "failed", "skipped"]
    steps: int
    tool_calls: int
    usd: float
    summary: str


class Discarded(_Strict):
    """A path not taken, with why."""

    kind: Literal["ruled_out", "rejected_call", "gate_rejection", "backfilled", "critic_downgrade", "not_tested"]
    text: str
    seq: int | None
    receipts: list[ReceiptLink]


class ChainLink(_Strict):
    kind: Literal["event", "root", "formula", "impact", "symptom"]
    source: str = Field(description="event ref or node id")
    target: str = Field(description="node id or 'eur'")
    label: str
    share: float | None = Field(description="explained share where it applies (LMDI share of the target's change)")
    status: Literal["tested", "untested"]
    receipts: list[ReceiptLink]


class CauseChain(_Strict):
    """Event -> root node in its segment -> formula hops -> EUR, for one supported incident."""

    incident_id: str
    links: list[ChainLink]
    text: str = Field(description="host-rendered one-liner")


class CostLine(_Strict):
    phase: Literal["detective", "critic", "ask"]
    model: str
    llm_calls: int
    input_tokens: int
    output_tokens: int
    usd: float


class CostView(_Strict):
    usd: float
    cap_usd: float
    llm_calls: int
    tool_calls: int
    cap_tool_calls: int
    replayed: bool = Field(description="true: recorded cost, nothing was spent now")
    lines: list[CostLine]


class CriticView(_Strict):
    result: Literal["upheld", "weakened", "refuted", "unavailable", "skipped"]
    model: str | None
    attempts: int
    reason: str
    checks: list[CheckRef]


PolicyName = Literal["propose", "propose_with_precedent", "suppress_denied", "suppress_no_effect"]


class Precedent(_Strict):
    """A remembered case that changed or annotated a proposal."""

    case_id: str
    sim_ts: datetime
    cause: str
    playbook_id: str | None
    decision: Literal["approve", "deny", "expired", "none"]
    effect: str | None
    policy: PolicyName
    note: str


class SecondOpinion(_Strict):
    """Only when the STL block ships (advisory, never changes a verdict)."""

    method: str = Field(description="'STL residual (statsmodels)'")
    z: float
    agrees: bool
    receipts: list[ReceiptLink]


class Board(_Strict):
    """Everything the UI shows about one investigation: competing hypotheses, grouped log, paths not taken,
    the cause chain, the counter-check, precedents and cost."""

    version: Literal["agent-board/1"]
    agent_run: str | None = Field(description="None for a Stage-2-only incident")
    incident_id: str | None
    anomaly_id: str | None
    through_seq: int = Field(description="last activity seq reflected (0 without agent records)")
    state: Literal["running", "done", "fallback", "budget"]
    profile: Literal["stage2", "v1", "v2"]
    hypotheses: list[HypothesisCard]
    counts: dict[HypothesisStatus, int] = Field(description="every status, summing to len(hypotheses)")
    groups: list[StepGroup]
    discarded: list[Discarded]
    chain: CauseChain | None
    critic: CriticView | None
    precedents: list[Precedent]
    second_opinion: SecondOpinion | None
    cost: CostView


# ---------------------------------------------------------------------------------------------- v2 activity payloads
#
# v2 records carry their structure in `ActivityRecord.args` (no new fields):
#
# * kind "hypothesis", tool "propose_hypotheses": {"declared": [DeclaredHypothesis, ...]} once per declaration;
#   kind "hypothesis": {"move": HypothesisMove} whenever the host's book moves a card;
# * every later detective "tool_call" record carries args["hypothesis_id"] naming the card it tests;
# * critic tool calls reuse "tool_call"/"tool_result" with role "skeptic" and call ids '<run_id>:c<n>';
#   kind "critic": Challenge fields plus "model" once the counter-check decided (or could not run);
# * kind "memory": a Precedent.


class DeclaredHypothesis(_Strict):
    """One competing hypothesis the v2 detective declared before its first causal check."""

    id: str = Field(description="'H1', ... as the model named it; the board keeps it")
    statement: str = Field(description="no digits")
    kind: HypothesisKind
    event_ref: str | None = None
    parent: str | None = Field(default=None, description="refines another hypothesis (tree depth at most 2)")
    decisive_check: str = Field(description="tool name of the cheapest check that could flip it")
    why_cheapest: str = ""


class HypothesisMove(_Strict):
    """The host's hypothesis book moved a card on a judged outcome (never on the model's word)."""

    id: str
    status: HypothesisStatus
    reason: str
    call_id: str | None = None


# ---------------------------------------------------------------------------------------------- Q2: critic


class Challenge(_Strict):
    """The counter-check's result. Deterministic rules over its receipts decide `downgrade`, never the model."""

    verdict: Literal["upheld", "weakened", "refuted", "unavailable"]
    downgrade: bool
    reason: str
    checks: list[dict[str, Any]] = Field(default_factory=list, description="goes into SkepticResult.checks")


class Critic(Protocol):
    """Q2 implements in src/argus/skeptic/critic.py. Called only when the rules would admit SUPPORTED_CAUSE."""

    def challenge(self, inv: Any, case: Any, selection: Any, supported: Any) -> Challenge: ...


# ---------------------------------------------------------------------------------------------- Q3: self-written SQL


class SqlJudgement(_Strict):
    accepted: bool
    rule: str | None = Field(default=None, description="first violated rule when rejected")
    outcome: Literal["holds", "fails"] | None = Field(default=None, description="None: not run or inconclusive")
    summary: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    receipt_id: str | None = None


class SqlValidator(Protocol):
    """`argus.evidence.sqlgate.validate`: never raises, never executes."""

    def __call__(self, sql: str) -> SqlJudgement: ...


class SqlCheckRunner(Protocol):
    """`argus.evidence.sqlgate.run_check(runner, sql, as_of, predict, purpose)`: validates, runs through the
    investigation's read-only `Runner` (an ordinary receipt), judges `predict` on the rows."""

    def __call__(
        self, runner: Any, sql: str, as_of: datetime, predict: dict[str, Any], purpose: str
    ) -> SqlJudgement: ...


# ---------------------------------------------------------------------------------------------- Q3: case memory


class CaseNote(_Strict):
    """A numbers-free note per decided case (advice, never evidence)."""

    case_id: str
    sim_ts: datetime
    fingerprint: str
    root_node: str
    segment_dims: list[str]
    verdict: str
    cause_kind: str | None = Field(default=None, description="e.g. 'deploy:ad-pacer'")
    cause_ref: str | None = Field(default=None, description="e.g. 'dep_ad-pacer_1.7.0'")
    deciding_checks: list[str] = Field(default_factory=list, description="tool names")
    playbook_id: str | None = None
    decision: Literal["approve", "deny", "expired", "none"] = "none"
    effect: Literal["VERIFIED", "NO_EFFECT", "INCONCLUSIVE"] | None = None


class CaseMemory(Protocol):
    """Q3 implements in src/argus/agent/memory.py."""

    def remember(self, note: CaseNote) -> None: ...

    def recall(
        self, *, root_node: str, segment: dict[str, str], cause_kind: str | None, as_of: datetime, limit: int = 3
    ) -> list[CaseNote]: ...


class ProposalPolicy(Protocol):
    """`argus.agent.memory.proposal_policy(notes, playbook_id, cause_ref)`: deterministic, host-side."""

    def __call__(self, notes: Sequence[CaseNote], playbook_id: str, cause_ref: str | None) -> PolicyName: ...
