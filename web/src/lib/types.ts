// TypeScript mirror of the C3, C4 and C5 contracts (src/argus/contracts). Keep field names identical.

export type Segment = Record<string, string>;
export type Direction = "up" | "down";

// ---------------------------------------------------------------- C3 graph

export type NodeKind = "additive" | "ratio" | "derived";
export type EdgeKind = "formula" | "breakdown" | "cause" | "evidence";
export type EdgeStatus = "VALID" | "SUPPORTED" | "PROBATION" | "PROPOSED" | "BROKEN";

export interface GraphNode {
  id: string;
  label: string;
  description: string;
  kind: NodeKind;
  unit: string;
  north_star: boolean;
  dims: string[];
  table: string | null;
  measure: string | null;
  numerator: string | null;
  denominator: string | null;
  expr: string | null;
  sql: string | null;
  state: string;
}

export interface EdgeTestResult {
  ran_at: string;
  passed: boolean | null;
  median_rel: number | null;
  p95_rel: number | null;
  max_rel_err: number | null;
  hours: number;
  receipts: string[];
  note: string;
}

export interface GraphEdge {
  id: string;
  kind: EdgeKind;
  target: string;
  sources: string[];
  expr: string | null;
  dim: string | null;
  lag_hours: number[] | null;
  status: EdgeStatus;
  weight: number;
  provenance: string;
  last_test: EdgeTestResult | null;
  note: string;
}

export interface LogSource {
  id: string;
  label: string;
  description: string;
}

export interface Graph {
  version: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  logs: LogSource[];
}

export interface GraphChange {
  seq: number;
  sim_ts: string;
  kind: string;
  node: string | null;
  edge: string | null;
  old_status: EdgeStatus | null;
  new_status: EdgeStatus | null;
  reason: string;
  receipts: string[];
}

// ---------------------------------------------------------------- C4 findings

export interface Receipt {
  id: string;
  sql: string;
  as_of: string;
  result_hash: string;
  rows: number;
  ms: number;
  purpose: string;
}

export interface Quantity {
  value: number;
  unit: string;
  receipt: string | null;
}

export interface TableFreshness {
  table: string;
  hour: string;
  completeness: number;
  status: "ok" | "pending";
}

export interface Anomaly {
  id: string;
  node: string;
  segment: Segment;
  direction: Direction;
  hour: string;
  detected_at: string;
  onset: string;
  observed: number;
  expected: number;
  band: [number, number];
  z: number;
  rule: string;
  data_confidence: number;
  receipts: string[];
}

export type Verdict = "SUPPORTED_CAUSE" | "HYPOTHESIS" | "EXPECTED" | "DATA_ISSUE" | "UNEXPLAINED";
export type IncidentState = "open" | "investigating" | "explained" | "monitoring" | "resolved";

export interface TrailStep {
  step: number;
  kind: string;
  tool: string;
  hypothesis: string | null;
  prediction: string | null;
  result: string;
  decision: string;
  why: string;
  receipts: string[];
  data: Record<string, unknown>;
}

export interface EvidenceRef {
  log: string;
  ref: string;
  ts: string;
  kind: string;
  description: string;
  scope: Record<string, string[]>;
}

export interface Contribution {
  node: string;
  share: number;
  value: number;
  receipt: string | null;
}

export interface Findings {
  anomaly_id: string;
  incident_id: string | null;
  verdict: Verdict;
  headline: string;
  as_of: string;
  window: { start: string; end: string };
  observed: { node: string; segment: Segment; observed: Quantity; expected: Quantity; change_pct: Quantity };
  root: { node: string; segment: Segment; direction: Direction; evidence: EvidenceRef | null; change_pct: Quantity } | null;
  decomposition: Contribution[];
  decomposed_node: string | null;
  impact: {
    node: string;
    segment: Segment;
    hours: number;
    per_hour: Quantity;
    gmv_eur_per_hour: Quantity;
    eur_so_far: Quantity;
  } | null;
  ruled_out: {
    hypothesis: string;
    prediction: string;
    result: "refuted" | "inconclusive";
    reason: string;
    evidence: EvidenceRef | null;
    receipts: string[];
  }[];
  uncertain: string[];
  explained_share: number;
  unexplained_share: number;
  trail: TrailStep[];
  skeptic: { verdict: "upheld" | "weakened" | "refuted"; checks: { check: string; result: string; receipts: string[] }[] } | null;
  cost: { queries: number; seconds: number; llm_calls: number; eur: number };
  suggested_action: { text: string; needs_approval: boolean } | null;
}

export interface Note {
  id: string;
  kind: "expected" | "data_issue" | "suppressed";
  sim_ts: string;
  node: string | null;
  segment: Segment;
  reason: string;
  numbers: Quantity[];
  receipts: string[];
}

export interface IncidentTransition {
  sim_ts: string;
  from_state: IncidentState | null;
  to_state: IncidentState;
  reason: string;
}

export interface Incident {
  id: string;
  fingerprint: string;
  title: string;
  verdict: Verdict;
  state: IncidentState;
  root_node: string;
  segment: Segment;
  direction: Direction;
  severity_eur: number;
  opened_at: string;
  updated_at: string;
  resolved_at: string | null;
  reopened: number;
  anomalies: string[];
  symptoms: string[];
  history: IncidentTransition[];
  findings: Findings;
}

// ---------------------------------------------------------------- C5 events

export interface TickPayload {
  as_of: string;
  hour: string;
  freshness: TableFreshness[];
  scored_nodes: string[];
  pending_nodes: string[];
  max_abs_z: Record<string, number>;
  open_incidents: number;
}

export interface EdgeStatusPayload {
  edge: string;
  old_status: EdgeStatus | null;
  new_status: EdgeStatus;
  result: EdgeTestResult;
}

export interface InvestigationStepPayload {
  anomaly_id: string;
  incident_id: string | null;
  step: TrailStep;
}

export interface SkepticStepPayload {
  incident_id: string;
  check: string;
  result: string;
  receipts: string[];
}

export interface IncidentUpdatedPayload {
  id: string;
  title: string;
  state: IncidentState;
  verdict: Verdict;
  root_node: string;
  segment: Segment;
  direction: Direction;
  severity_eur: number;
  change: "opened" | "updated" | "state" | "reopened";
  reason: string;
}

export type ArgusEvent =
  | { seq: number; sim_ts: string; type: "tick"; payload: TickPayload }
  | { seq: number; sim_ts: string; type: "attention"; payload: { scores: Record<string, number> } }
  | { seq: number; sim_ts: string; type: "edge_status"; payload: EdgeStatusPayload }
  | { seq: number; sim_ts: string; type: "anomaly_opened"; payload: Anomaly }
  | { seq: number; sim_ts: string; type: "investigation_step"; payload: InvestigationStepPayload }
  | { seq: number; sim_ts: string; type: "skeptic_step"; payload: SkepticStepPayload }
  | { seq: number; sim_ts: string; type: "incident_updated"; payload: IncidentUpdatedPayload }
  | { seq: number; sim_ts: string; type: "note_logged"; payload: Note }
  | { seq: number; sim_ts: string; type: "graph_changed"; payload: GraphChange }
  | { seq: number; sim_ts: string; type: "bench_progress"; payload: Record<string, unknown> }
  | { seq: number; sim_ts: string; type: "challenge_state"; payload: Record<string, unknown> };

export type EventType = ArgusEvent["type"];

export const EVENT_TYPES: EventType[] = [
  "tick",
  "attention",
  "edge_status",
  "anomaly_opened",
  "investigation_step",
  "skeptic_step",
  "incident_updated",
  "note_logged",
  "graph_changed",
  "bench_progress",
  "challenge_state",
];

export interface ReplayStatus {
  playing: boolean;
  finished: boolean;
  speed: number;
  position: number;
  total: number;
  sim_ts: string | null;
  loop: boolean;
}

export interface Health {
  ok: boolean;
  mode: "replay" | "live";
  contract_version: string;
  stream: string;
  last_seq: number;
  replay: ReplayStatus | null;
  recording: { scenario: string | null; seed: number | null; source: string; description: string } | null;
  rerun: boolean;
}

export interface RerunResult {
  receipt: string;
  as_of: string;
  expected_hash: string;
  result_hash: string;
  matches: boolean;
  rows: number;
  ms: number;
  world: string;
}
