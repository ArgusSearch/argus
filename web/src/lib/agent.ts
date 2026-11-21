// Client for the Argus Agent routes (docs/ext/agent.md, frozen interface agent-types/1 in
// src/argus/agent/types.py). The routes sit outside the C5 route table: `GET /agent/health` is the feature probe,
// and every surface that uses them stays hidden (or falls back) while it answers 404.

import { withRun } from "./agentDemo";
import { ApiError } from "./api";
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

export interface ActivityRecord {
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
  models: Record<string, string> | string[];
  caps: Record<string, unknown>;
  usd: number;
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
  answer: string;
  claims: VerifiedClaim[];
  receipt_links: ReceiptLink[];
  activity_cursor: number | null;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
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

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

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
  actions: () => call<ProposalView[]>(withRun("/agent/actions")),
  decide: (id: string, verb: "approve" | "deny", digest: string, key = idempotencyKey()) =>
    call<ProposalView>(withRun(`/agent/actions/${encodeURIComponent(id)}/${verb}`), post({ digest, idempotency_key: key })),
  ask: (question: string, incidentId?: string | null, conversationId?: string | null) =>
    call<AskAnswer>(withRun("/agent/ask"), post({ question, incident_id: incidentId ?? null, conversation_id: conversationId ?? null })),
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
