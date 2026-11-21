// The village's inputs. A tape is one recorded run in the shape of lane D's presentation export
// (fixtures/agent/v1/README.md): C5 events, the agent's activity log and its proposals, plus the approve and
// deny continuations that only play after an operator decides. The agent types mirror the frozen interface
// `src/argus/agent/types.py` (interface version agent-types/1); keep field names identical.

import type { ArgusEvent, Segment } from "../lib/types";

// ---------------------------------------------------------------- lane A mirror (agent-types/1)

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

export type AgentStage = "WATCH" | "TRIAGE" | "PLAN" | "ACT" | "OBSERVE" | "VERIFY" | "REPORT" | "PROPOSE" | "AWAIT_OPERATOR" | "ASK";

export interface ReceiptLink {
  run_id: string;
  world_revision: string;
  receipt_id: string;
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
  receipt_refs?: ReceiptLink[];
}

export interface ActivityRecord {
  seq: number;
  run_id: string | null;
  sim_ts: string;
  kind: ActivityKind;
  stage: AgentStage;
  actor: "model" | "host" | "operator";
  text: string;
  anomaly_id?: string | null;
  incident_id?: string | null;
  action_id?: string | null;
  tool?: string | null;
  args?: Record<string, unknown> | null;
  observation?: Observation | null;
  receipt_links?: ReceiptLink[];
  model?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  usd?: number | null;
  /** replay: the action whose approval releases this record */
  gate_action?: string | null;
}

export type ProposalState =
  | "AWAIT_OPERATOR"
  | "DENIED"
  | "EXPIRED"
  | "APPLYING"
  | "APPLIED"
  | "VERIFYING"
  | "VERIFIED"
  | "NO_EFFECT"
  | "INCONCLUSIVE";

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
  success_rule: { node: string; scope: Record<string, string[]>; rule: string; hours: number; comparator: string };
  evidence_refs: ReceiptLink[];
  decision: { decision: "approve" | "deny"; principal: string; at: string } | null;
  effect: { state: "VERIFIED" | "NO_EFFECT" | "INCONCLUSIVE"; checked_at: string; summary: string } | null;
}

// ---------------------------------------------------------------- tapes

/** An incident's suggested action from its C4 findings: what the operator is asked to approve on a C5-only tape. */
export interface TapeIncident {
  id: string;
  title: string;
  segment: Segment;
  suggested_action: { text: string; needs_approval: boolean } | null;
}

/** One continuation of a tape: what plays after the operator approved or denied. */
export interface TapePart {
  events: ArgusEvent[];
  activity: ActivityRecord[];
  actions: ProposalView[];
}

/** A new metric placing itself in the graph (lane H, `GET /graph/metrics`, PlacementResult), as the village shows it. */
export interface TapePlacement {
  metric: { name: string; description: string };
  placed_as: "EXACT" | "NEW_DIMENSION" | "ALIAS" | "AMBIGUOUS" | "REJECTED";
  summary: string;
  definition: string;
  as_of: string;
  tried: string[];
  passed: string[];
  uncertain: string[];
  receipts: string[];
}

export interface VillageTape extends TapePart {
  version: 1;
  /** "s1", "s4", or "live" */
  scenario: string;
  title: string;
  /** where the recording came from, shown in the corner HUD */
  source: string;
  /** metric id to its label, from the run's C3 graph */
  labels: Record<string, string>;
  incidents: TapeIncident[];
  continuations: { approve?: TapePart; deny?: TapePart };
  /** new metrics placed in the graph, in the order they were placed */
  placements?: TapePlacement[];
}

export type Decision = "approve" | "deny";
