// The graph extension API (`GET/POST /graph/metrics`, src/argus/graph/extension.py): a new metric (C2) places
// itself in the running graph. These mirror `PlacementResult` and `ExtensionState`.

import type { EdgeTestResult, GraphChange, GraphEdge, GraphNode, Receipt } from "../lib/types";

export type PlacedAs = "EXACT" | "NEW_DIMENSION" | "ALIAS" | "AMBIGUOUS" | "REJECTED";
export type Lifecycle = "proposed" | "tested" | "accepted" | "rejected";

export interface MetricDefinition {
  name: string;
  description: string;
  sql: string;
}

export interface Certificate {
  metric: string;
  placed_as: PlacedAs;
  summary: string;
  tried: string[];
  passed: string[];
  uncertain: string[];
  edges: string[];
  receipts: string[];
}

export interface CandidateView {
  edge: GraphEdge;
  reads: string;
  lifecycle: Lifecycle;
  why: string;
  verdict: string;
  proposed_by: string;
  result: EdgeTestResult | null;
}

export interface PlacementCard {
  id: string;
  subject: string;
  subject_kind: "metric" | "node" | "edge";
  title: string;
  before: string;
  after: string;
  tone: "good" | "watch" | "bad";
  evidence: string;
  detail: string;
  diff: string | null;
}

export interface PlacementResult {
  metric: MetricDefinition;
  placed_as: PlacedAs;
  summary: string;
  definition: string;
  mode: "live" | "recorded";
  world: string;
  as_of: string;
  certificate: Certificate;
  node: GraphNode | null;
  alias_of: string | null;
  alias_scale: number;
  segment: Record<string, string>;
  parents: string[];
  alternatives: string[];
  candidates: CandidateView[];
  added_edges: GraphEdge[];
  repair: { factor: number; sql: string; diff: string } | null;
  cards: PlacementCard[];
  changes: GraphChange[];
  receipts: Receipt[];
  requires: string[];
}

export interface ExtensionState {
  mode: "live" | "replay";
  stream: string;
  version: number;
  placements: PlacementResult[];
  recorded: MetricDefinition[];
}
