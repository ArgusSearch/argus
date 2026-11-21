// Everything the 3D graph shows, derived from the two props of the scene through pure functions.
// The state rules are the ones of the 2D graph (GraphView) and are pinned by web/test/fx/scene/model.test.ts.

import { focusOf, freshAnomaly, isRuledOut, type RunView, type StepView } from "../../lib/store";
import type { EdgeStatus, EvidenceRef, Graph } from "../../lib/types";
import { layout, type Placement } from "./layout";

export type NodeTone = "normal" | "wiggle" | "alarm" | "symptom" | "root" | "resolved";
export type ScenePhase = "idle" | "anomaly" | "investigating" | "verdict" | "resolved";

export interface SceneNode {
  id: string;
  kind: "metric" | "log";
  label: string;
  northStar: boolean;
  tone: NodeTone;
  /** |z| as sent by the API, never interpolated for display */
  z: number | null;
  /** attention, 0 to 1 */
  heat: number;
  focus: boolean;
  scored: boolean;
  /** "root cause", "anomaly", "symptom", "checking", "segment search", "resolved" */
  tag: string | null;
  position: [number, number, number];
}

export interface SceneLink {
  id: string;
  source: string;
  target: string;
  /** breakdown edges stay on the node, as in the 2D graph */
  kind: "formula" | "cause" | "evidence" | "definition";
  status: EdgeStatus | null;
  focus: boolean;
}

export interface SceneModel {
  nodes: SceneNode[];
  links: SceneLink[];
  /** node and log ids the current investigation touched, in step order, for the numbered trace */
  trace: { id: string; step: number }[];
  phase: ScenePhase;
  /** number of ticks folded so far; a change triggers the hourly pulse */
  ticks: number;
  /** ids present in this graph version but not in the previous one */
  added: string[];
}

/** The short names the 2D graph uses where the full label does not fit a block. */
export const SHORT_LABEL: Readonly<Record<string, string>> = {
  payment_success_rate: "Payment success",
  impressions_per_session: "Impr. per session",
  aov: "Order value (AOV)",
  cvr: "Conversion",
  payment_attempts: "Pay attempts",
  payment_successes: "Pay successes",
};

const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);

/** The investigation the graph shows: the latest anomaly and its steps (the trail shows the same one). */
export function currentInvestigation(view: RunView): { anomaly: RunView["anomalies"][number]; steps: StepView[] } | null {
  const anomaly = view.anomalies[view.anomalies.length - 1];
  if (!anomaly) return null;
  return { anomaly, steps: view.steps.filter((s) => s.anomalyId === anomaly.id) };
}

/** Logs and metrics a step of the current investigation ruled out (refuted holdouts): the scene dims them. */
export function ruledOut(view: RunView): Set<string> {
  const out = new Set<string>();
  const current = currentInvestigation(view);
  if (!current) return out;
  const earlier: StepView[] = [];
  for (const s of current.steps) {
    const focus = focusOf(s.step, current.anomaly.node, earlier);
    if (isRuledOut(s.step.decision)) {
      for (const id of focus.logs) out.add(id);
      for (const id of focus.nodes) if (id !== current.anomaly.node) out.add(id);
    }
    earlier.push(s);
  }
  return out;
}

function phaseOf(view: RunView): ScenePhase {
  const current = currentInvestigation(view);
  if (!current) return "idle";
  const { anomaly, steps } = current;
  const ids = new Set(steps.map((s) => s.incidentId).filter((id): id is string => id !== null));
  const incident = Object.values(view.incidents).find((inc) => ids.has(inc.id) || inc.root_node === anomaly.node);
  if (incident?.state === "resolved") return "resolved";
  if (steps.some((s) => s.step.kind === "verdict")) return "verdict";
  return steps.length ? "investigating" : "anomaly";
}

function traceOf(view: RunView, placed: Map<string, Placement>): SceneModel["trace"] {
  const current = currentInvestigation(view);
  if (!current) return [];
  const out: SceneModel["trace"] = [];
  const earlier: StepView[] = [];
  for (const s of current.steps) {
    const focus = focusOf(s.step, current.anomaly.node, earlier);
    for (const id of new Set([...focus.nodes, ...focus.logs])) {
      if (placed.has(id)) out.push({ id, step: s.step.step });
    }
    earlier.push(s);
  }
  return out;
}

export function sceneModel(graph: Graph, view: RunView, previous?: SceneModel): SceneModel {
  const placed = layout(graph);
  const at = (id: string): [number, number, number] => placed.get(id)?.position ?? [0, 0, 0];

  // incident and note states, exactly as GraphView derives them
  const roots = new Map<string, string>();
  const symptoms = new Set<string>();
  const resolved = new Set<string>();
  for (const inc of Object.values(view.incidents)) {
    if (inc.state === "resolved") resolved.add(inc.root_node);
    else roots.set(inc.root_node, inc.verdict === "SUPPORTED_CAUSE" ? "root cause" : "anomaly");
  }
  for (const note of view.notes) {
    if (note.node && note.reason.includes("symptom of")) symptoms.add(note.node);
  }
  const focusNodes = new Set(view.focus?.nodes ?? []);
  const focusLogs = new Set(view.focus?.logs ?? []);
  const focusEdges = new Set((view.focus?.edges ?? []).filter((e) => !e.startsWith("b_")));
  const split = (view.focus?.edges ?? []).filter((e) => e.startsWith("b_"));
  const fresh = freshAnomaly(view);
  const scored = new Set(view.tick?.scored_nodes ?? []);
  const { alarm_z, wiggle_z } = view.thresholds;

  const nodes: SceneNode[] = graph.nodes.map((n) => {
    const raw = fresh?.node === n.id ? Math.abs(fresh.z) : view.tick?.max_abs_z[n.id];
    const z = raw !== undefined && Number.isFinite(raw) ? raw : null;
    let tone: NodeTone = "normal";
    let tag: string | null = null;
    if (z !== null && z >= wiggle_z) tone = "wiggle";
    if (symptoms.has(n.id) && roots.size) {
      tone = "symptom";
      tag = "symptom";
    }
    if (z !== null && z >= alarm_z) tone = "alarm";
    const root = roots.get(n.id);
    if (root !== undefined) {
      tone = "root";
      tag = root;
    } else if (resolved.has(n.id) && tone !== "alarm") {
      tone = "resolved";
      tag = "resolved";
    }
    const focus = focusNodes.has(n.id);
    if (focus && split.some((e) => e.startsWith(`b_${n.id}_`))) tag = "segment search";
    else if (focus) tag = tag ?? "checking";
    return {
      id: n.id,
      kind: "metric",
      label: SHORT_LABEL[n.id] ?? n.label,
      northStar: n.north_star,
      tone,
      z,
      heat: clamp01(view.attention[n.id] ?? 0),
      focus,
      scored: scored.has(n.id) || fresh?.node === n.id,
      tag,
      position: at(n.id),
    };
  });
  for (const l of graph.logs) {
    const focus = focusLogs.has(l.id);
    nodes.push({
      id: l.id,
      kind: "log",
      label: l.label,
      northStar: false,
      tone: "normal",
      z: null,
      heat: 0,
      focus,
      scored: false,
      tag: focus ? "checking" : null,
      position: at(l.id),
    });
  }

  // typed edges, one link per source; a ratio's definition unless the ratio is a factor of a formula
  const links: SceneLink[] = [];
  const touches = (id: string) => focusNodes.has(id) || focusLogs.has(id);
  for (const e of graph.edges) {
    if (e.kind === "breakdown") continue;
    const status = view.edges[e.id]?.status ?? e.status;
    for (const s of e.sources) {
      if (!placed.has(s) || !placed.has(e.target)) continue;
      const named = focusEdges.has(e.id) && (focusNodes.size <= 1 || focusNodes.has(e.target) || touches(s));
      const ends = focusNodes.has(e.target) && touches(s);
      links.push({ id: `${e.id}:${s}`, source: s, target: e.target, kind: e.kind, status, focus: named || ends });
    }
  }
  const factors = new Set(graph.edges.filter((e) => e.kind === "formula").flatMap((e) => e.sources));
  for (const n of graph.nodes) {
    if (n.kind !== "ratio" || factors.has(n.id)) continue;
    for (const part of [n.numerator, n.denominator]) {
      if (!part || !placed.has(part)) continue;
      const focus = focusNodes.has(n.id) && touches(part);
      links.push({ id: `def:${n.id}:${part}`, source: part, target: n.id, kind: "definition", status: null, focus });
    }
  }

  const before = previous ? new Set(previous.nodes.map((n) => n.id)) : null;
  const added = before ? nodes.filter((n) => !before.has(n.id)).map((n) => n.id) : [];

  return { nodes, links, trace: traceOf(view, placed), phase: phaseOf(view), ticks: view.ticks, added };
}

/**
 * The affected path of the open investigation: the anomalous metric, everything its formulas move downstream
 * (what the anomaly costs), and the logs whose evidence held. Empty when nothing is under investigation or the
 * incident is resolved. The scene lights this path and lets the rest of the graph recede.
 */
export function incidentPath(model: SceneModel, view: RunView): Set<string> {
  const path = new Set<string>();
  const current = currentInvestigation(view);
  if (!current || model.phase === "idle" || model.phase === "resolved") return path;
  path.add(current.anomaly.node);
  for (let grew = true; grew; ) {
    grew = false;
    for (const l of model.links) {
      if (l.kind === "formula" && path.has(l.source) && !path.has(l.target)) {
        path.add(l.target);
        grew = true;
      }
    }
  }
  for (const s of current.steps) {
    const event = s.step.data?.event as EvidenceRef | undefined;
    if (s.step.kind === "holdout" && event?.log && !isRuledOut(s.step.decision)) path.add(event.log);
  }
  return path;
}

/** The hover title of a block: the same text the 2D graph shows. */
export function nodeTitle(graph: Graph, node: Pick<SceneNode, "id" | "kind" | "scored">): string {
  const n = node.kind === "metric" ? graph.nodes.find((x) => x.id === node.id) : undefined;
  if (!n) return "log of state changes (evidence source)";
  return `${n.label}: ${n.description}${node.scored ? "" : " (scored when an investigation needs it)"}`;
}
