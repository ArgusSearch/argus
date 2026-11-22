// Client for the Argus Agent routes (docs/ext/agent.md, frozen interface agent-types/1 in
// src/argus/agent/types.py). The routes sit outside the C5 route table: `GET /agent/health` is the feature probe,
// and every surface that uses them stays hidden (or falls back) while it answers 404.

import { demoRunId, withRun } from "./agentDemo";
import { ApiError, apiFetch } from "./api";
import { publicApi, remoteGuidedRun } from "./deployment";
import type { Receipt } from "./types";

export type AgentMode = "live" | "record" | "replay" | "off";

export interface ReceiptLink {
  run_id: string;
  world_revision: string;
  receipt_id: string;
}

export interface FactHandle {
  id: string;
  label: string;
  value: number;
  unit: string;
  receipts: ReceiptLink[];
}

export interface Observation {
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  hypothesis: string | null;
  prediction: string | null;
  expect: string | null;
  outcome: string | null;
  summary: string;
  data: Record<string, unknown>;
  fact_handles: FactHandle[];
  receipt_refs: ReceiptLink[];
  availability: "ok" | "unavailable" | "rejected" | "error";
}

export interface VerifiedClaim {
  claim_id: string;
  kind: string;
  subject: string;
  segment: Record<string, string>;
  as_of: string;
  world_revision: string;
  value: number | null;
  unit: string | null;
  display: string;
  receipts: ReceiptLink[];
}

export type ProposalState = "AWAIT_OPERATOR" | "DENIED" | "EXPIRED" | "APPLYING" | "APPLIED" | "VERIFYING" | "VERIFIED" | "NO_EFFECT" | "INCONCLUSIVE";

export interface ProposalView {
  id: string;
  digest: string;
  state: ProposalState;
  run_id: string;
  incident_ref: string;
  playbook_id: string;
  action: string;
  scope: Record<string, string[]>;
  effective_at: string;
  expires_at: string;
  success_rule: { node: string; scope: Record<string, string[]>; rule: string; hours: number; comparator: "expectation" | "untreated_twin" };
  evidence_refs: ReceiptLink[];
  decision: { decision: "approve" | "deny"; principal: string; at: string } | null;
  effect: { state: "VERIFIED" | "NO_EFFECT" | "INCONCLUSIVE"; checked_at: string; summary: string; claims: VerifiedClaim[]; receipt_refs: ReceiptLink[] } | null;
}

export type ActivityKind =
  | "run_started"
  | "thought"
  | "tool_call"
  | "tool_result"
  | "gate"
  | "report"
  | "rejected"
  | "action_proposed"
  | "action_decided"
  | "action_applied"
  | "effect_checked"
  | "budget"
  | "fallback"
  | "chat_question"
  | "chat_answer"
  | "watch"
  | "run_finished";

/**
 * Kinds only profile-v2 recordings emit (`src/argus/agent/types.py`). Not part of `ActivityKind` yet, so views keyed
 * by it stay exhaustive; a view must render any kind it does not know as a plain line before v2 plays.
 */
export type ActivityKindV2 = "hypothesis" | "critic" | "memory";

/** The seven agent roles (lane G's village, web/src/village/roles.ts): who did a step. */
export type AgentRole = "watcher" | "cartographer" | "detective" | "market" | "skeptic" | "narrator" | "operator";

export const AGENT_ROLES: readonly AgentRole[] = ["watcher", "cartographer", "detective", "market", "skeptic", "narrator", "operator"];

export interface ActivityRecord {
  /** who did the step; derived by `roleOf` while the API does not send it */
  role?: AgentRole;
  seq: number;
  run_id: string | null;
  sim_ts: string;
  kind: ActivityKind;
  stage: string;
  actor: "model" | "host" | "operator";
  text: string;
  anomaly_id: string | null;
  incident_id: string | null;
  action_id: string | null;
  tool: string | null;
  args: Record<string, unknown> | null;
  observation: Observation | null;
  receipt_links: ReceiptLink[];
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  usd: number | null;
  gate_action: string | null;
}

export interface RunSummary {
  run_id: string;
  kind: "investigate" | "ask" | "morning" | "verify_effect";
  mode: AgentMode;
  sim_ts: string;
  anomaly_id: string | null;
  incident_id: string | null;
  status: "running" | "done" | "budget" | "failed" | "fallback";
  stop_reason: string | null;
  llm_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  gate: { claimed: string; admitted: string; reasons: string[] } | null;
  fallback: string | null;
}

export interface AgentHealth {
  enabled: boolean;
  mode: AgentMode;
  /** why the agent is off (lane A: "This is a replay: the recorded agent run plays in the demo playback") */
  reason?: string;
  models: Record<string, string> | string[];
  caps: Record<string, unknown>;
  usd: number;
  /** agent profile ("v1" recorded behaviour, "v2" with the new techniques) and its switched-on features */
  profile?: "v1" | "v2";
  features?: string[];
  /** set when the server serves `/agent/boards` */
  board_version?: "agent-board/1";
  public_limits?: PublicLimits;
}

export interface PublicLimits {
  daily_usd?: number;
  spent_today_usd?: number;
  session_hour?: number;
  ip_hour?: number;
  watcher_hour?: number;
  input_tokens?: number;
  output_tokens?: number;
  turns?: { ask: number; investigate: number; critic: number };
  message?: string | null;
  stored_investigation?: { stored_at: string; title: string; report: string | null } | null;
}

/** The derived investigation board (`GET /agent/boards`, `src/argus/agent/types.py` `Board`, version agent-board/1). */
export type HypothesisStatus = "open" | "supported" | "ruled_out" | "inconclusive" | "not_tested";
export type HypothesisKind = "event" | "data" | "planned" | "market" | "mix" | "recurring" | "segment" | "other";

export interface CheckRef {
  seq: number | null;
  call_id: string | null;
  step: number | null;
  tool: string;
  by: "host" | "detective" | "critic";
  status: "validated" | "refuted" | "inconclusive" | "observed" | "rejected";
  outcome: string | null;
  summary: string;
  receipts: ReceiptLink[];
}

export interface HypothesisCard {
  id: string;
  parent: string | null;
  statement: string;
  kind: HypothesisKind;
  subject: string | null;
  source: "host" | "model" | "critic";
  status: HypothesisStatus;
  reason: string;
  decisive_check: string | null;
  checks: CheckRef[];
}

export interface StepGroup {
  id: string;
  title: string;
  phase: "opening" | "hypotheses" | "checks" | "critic" | "verdict" | "report" | "action" | "effect" | "ask";
  role: AgentRole;
  first_seq: number;
  last_seq: number;
  status: "running" | "done" | "failed" | "skipped";
  steps: number;
  tool_calls: number;
  usd: number;
  summary: string;
}

export interface Discarded {
  kind: "ruled_out" | "rejected_call" | "gate_rejection" | "backfilled" | "critic_downgrade" | "not_tested";
  text: string;
  seq: number | null;
  receipts: ReceiptLink[];
}

export interface ChainLink {
  kind: "event" | "root" | "formula" | "impact" | "symptom";
  source: string;
  target: string;
  label: string;
  share: number | null;
  status: "tested" | "untested";
  receipts: ReceiptLink[];
}

export interface CauseChain {
  incident_id: string;
  links: ChainLink[];
  text: string;
}

export interface CostLine {
  phase: "detective" | "critic" | "ask";
  model: string;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
}

export interface CostView {
  usd: number;
  cap_usd: number;
  llm_calls: number;
  tool_calls: number;
  cap_tool_calls: number;
  /** true: a recorded run, nothing was spent now */
  replayed: boolean;
  lines: CostLine[];
}

export interface CriticView {
  result: "upheld" | "weakened" | "refuted" | "unavailable" | "skipped";
  model: string | null;
  attempts: number;
  reason: string;
  checks: CheckRef[];
}

export interface Precedent {
  case_id: string;
  sim_ts: string;
  cause: string;
  playbook_id: string | null;
  decision: "approve" | "deny" | "expired" | "none";
  effect: string | null;
  policy: "propose" | "propose_with_precedent" | "suppress_denied" | "suppress_no_effect";
  note: string;
}

export interface SecondOpinion {
  method: string;
  z: number;
  agrees: boolean;
  receipts: ReceiptLink[];
}

export interface Board {
  version: "agent-board/1";
  /** null for a Stage-2-only incident */
  agent_run: string | null;
  incident_id: string | null;
  anomaly_id: string | null;
  through_seq: number;
  state: "running" | "done" | "fallback" | "budget";
  profile: "stage2" | "v1" | "v2";
  hypotheses: HypothesisCard[];
  /** every status, summing to hypotheses.length */
  counts: Record<HypothesisStatus, number>;
  groups: StepGroup[];
  discarded: Discarded[];
  chain: CauseChain | null;
  critic: CriticView | null;
  precedents: Precedent[];
  second_opinion: SecondOpinion | null;
  cost: CostView;
}

/**
 * A receipt as the agent routes serve it: the C4 receipt itself (live), or a recorded proof (the demo's sealed
 * tape) that also carries the captured result rows and whether its hash was verified when it was captured.
 */
export interface AgentReceipt extends Receipt {
  columns?: string[];
  captured_rows?: unknown[][];
  verified_at_capture?: boolean;
}

/** Either shape the routes answer with, as one receipt. */
export function normalizeReceipt(raw: unknown): AgentReceipt {
  const r = raw as { receipt?: Receipt; columns?: string[]; rows?: unknown; verified_at_capture?: boolean };
  if (r && typeof r === "object" && r.receipt && typeof r.receipt === "object") {
    return { ...r.receipt, columns: r.columns ?? [], captured_rows: Array.isArray(r.rows) ? (r.rows as unknown[][]) : [], verified_at_capture: r.verified_at_capture };
  }
  return raw as AgentReceipt;
}

export interface AskAnswer {
  status: string;
  /** send it back with a follow-up question: the follow-up keeps the incident scope and sees the earlier turns */
  conversation_id?: string | null;
  answer: string;
  claims: VerifiedClaim[];
  receipt_links: ReceiptLink[];
  activity_cursor: number | null;
  /** the agent run that answered (its checks are in the activity log); null when no run was needed */
  run_id?: string | null;
  /** why the status is what it is, for a refused or unavailable answer */
  reason?: string | null;
  usd?: number | null;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, { credentials: "include", ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return (await res.json()) as T;
}

const post = (body: unknown, headers: Record<string, string> = {}): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json", ...headers },
  body: JSON.stringify(body),
});

/**
 * The operator session (lane C, docs/ext/remediation.md): `POST /agent/operator/session` sets an HttpOnly cookie
 * on /agent and returns a CSRF token; every decision sends the token in `X-Argus-CSRF`. Opened on the first
 * decision and again when the server forgot it (a restarted API answers 403). A server without the route (the
 * demo playback) takes decisions without one.
 */
const CSRF_HEADER = "X-Argus-CSRF";
let operator: { path: string; token: string | null } | null = null;

async function operatorToken(path: string, fresh = false): Promise<string | null> {
  if (operator?.path === path && !fresh) return operator.token;
  try {
    const session = await call<{ principal: string; csrf_token: string }>(path, post({}));
    operator = { path, token: session.csrf_token };
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) operator = { path, token: null };
    else throw e;
  }
  return operator.token;
}

async function decideWithSession<T>(path: string, body: unknown, scope: "current" | "live"): Promise<T> {
  const session = "/agent/operator/session";
  const sessionPath = scope === "live" ? session : withRun(session);
  const decisionPath = scope === "live" ? path : withRun(path);
  const send = (token: string | null) => call<T>(decisionPath, post(body, token ? { [CSRF_HEADER]: token } : {}));
  try {
    return await send(await operatorToken(sessionPath));
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) return send(await operatorToken(sessionPath, true));
    throw e;
  }
}

/** A fresh key per decision click: the route is idempotent per key, so a retried request cannot decide twice. */
export function idempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export const agentApi = {
  /**
   * The feature probe: null while the agent routes are not mounted or the API is down. It reads the API's own
   * route table first, so a build without the agent never requests a missing route (no 404 in the console).
   */
  health: async (): Promise<AgentHealth | null> => {
    try {
      if (publicApi) return await call<AgentHealth>("/agent/health");
      const table = await call<{ paths?: Record<string, unknown> }>("/openapi.json");
      if (!table.paths || !("/agent/health" in table.paths)) return null;
      return await call<AgentHealth>("/agent/health");
    } catch {
      return null;
    }
  },
  // every agent route is pinned to the demo presentation while one plays (withRun appends its run_id)
  activity: (since = 0) => call<{ stream: string; mode: AgentMode; records: ActivityRecord[] }>(withRun(`/agent/activity?since=${since}`)),
  runs: () => call<RunSummary[]>(withRun("/agent/runs")),
  boards: (since = 0) => call<{ boards: Board[]; next_cursor: number }>(withRun(`/agent/boards?since=${since}`)),
  incidentBoard: (id: string) => call<Board>(withRun(`/agent/boards/incident/${encodeURIComponent(id)}`)),
  actions: () => call<ProposalView[]>(withRun("/agent/actions")),
  decide: (id: string, verb: "approve" | "deny", digest: string, key = idempotencyKey(), scope: "current" | "live" = "current") =>
    decideWithSession<ProposalView>(`/agent/actions/${encodeURIComponent(id)}/${verb}`, { digest, idempotency_key: key }, scope),
  /** `signal` stops waiting for the answer (the server's run still finishes and is billed) */
  ask: async (question: string, incidentId?: string | null, conversationId?: string | null, signal?: AbortSignal) => {
    const body = { question, incident_id: incidentId ?? null, conversation_id: conversationId ?? null };
    const path = withRun("/agent/ask");
    const send = (token: string | null) => call<AskAnswer>(path, { ...post(body, token ? { [CSRF_HEADER]: token } : {}), signal });
    if (!publicApi || remoteGuidedRun || demoRunId()) return send(null);
    const session = "/agent/operator/session";
    try {
      return await send(await operatorToken(session));
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) return send(await operatorToken(session, true));
      throw error;
    }
  },
  receipt: async (link: ReceiptLink): Promise<AgentReceipt> =>
    normalizeReceipt(
      await call<unknown>(withRun(`/agent/receipts/${encodeURIComponent(link.run_id)}/${encodeURIComponent(link.world_revision)}/${encodeURIComponent(link.receipt_id)}`)),
    ),
  /** A C4 receipt the demo presentation revealed (its own route, pinned to the presentation). */
  demoReceipt: async (id: string): Promise<AgentReceipt> => normalizeReceipt(await call<unknown>(withRun(`/demo/receipts/${encodeURIComponent(id)}`))),
};

/** A proposal that is still moving: the page polls it until it settles. */
export function settling(state: ProposalState): boolean {
  return state === "APPLYING" || state === "APPLIED" || state === "VERIFYING";
}

/** The role a check belongs to, by its tool (the same mapping as lane G's village beats). */
export function roleOfTool(tool: string | null | undefined, kind?: string): AgentRole {
  switch (tool) {
    case "check_freshness":
      return "watcher";
    case "check_identities":
      return "cartographer";
    case "decompose_formula":
      return kind === "impact" ? "narrator" : "cartographer";
    case "holdout_check":
    case "placebo_test":
    case "skeptic":
      return "skeptic";
    case "check_control_group":
    case "market_control":
      return "market";
    case "counterfactual_impact":
    case "verdict":
      return "narrator";
    case "propose_action":
      return "operator";
    default:
      return "detective";
  }
}

/** Who did an activity step: the record's own role when the API sends one, else by its kind and tool. */
export function roleOf(rec: ActivityRecord): AgentRole {
  if (rec.role && AGENT_ROLES.includes(rec.role)) return rec.role;
  switch (rec.kind) {
    case "watch":
      return "watcher";
    case "gate":
    case "rejected":
      return "skeptic";
    case "report":
    case "chat_question":
    case "chat_answer":
    case "run_finished":
      return "narrator";
    case "action_proposed":
    case "action_decided":
    case "action_applied":
    case "effect_checked":
      return "operator";
    case "run_started":
    case "budget":
    case "fallback":
      return "detective";
    default:
      return roleOfTool(rec.tool ?? rec.observation?.tool ?? null);
  }
}
