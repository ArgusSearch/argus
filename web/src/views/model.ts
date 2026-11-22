// Pure helpers shared by the views: what state a metric is in right now, and the effective status of an edge.
// Everything here reads the folded RunView; nothing computes a number that is shown as a measurement.

import { freshAnomaly, type RunView } from "../lib/store";
import type { EdgeStatus, Graph, GraphEdge } from "../lib/types";

export type MetricState = "checking" | "root" | "alarm" | "symptom" | "wiggle" | "pending" | "resolved" | "normal" | "unscored";

export interface MetricStatus {
  state: MetricState;
  /** |z| of the latest scored hour, as the watcher reported it; null when the metric was not scored */
  z: number | null;
  label: string;
}

const LABEL: Record<MetricState, string> = {
  checking: "being checked",
  root: "root cause",
  alarm: "alarm",
  symptom: "silenced symptom",
  wiggle: "wiggle",
  pending: "pending data",
  resolved: "resolved",
  normal: "normal",
  unscored: "not scored this hour",
};

export function stateLabel(state: MetricState): string {
  return LABEL[state];
}

/** The state of one metric, with the same rules the graph uses for its node colors. */
export function metricStatus(view: RunView, id: string): MetricStatus {
  const fresh = freshAnomaly(view);
  const scored = fresh?.node === id || (view.tick?.scored_nodes ?? []).includes(id);
  const raw = fresh?.node === id ? fresh.z : view.tick?.max_abs_z[id];
  const z = raw === undefined || !Number.isFinite(raw) ? null : Math.abs(raw);

  let openRoot: string | null = null;
  let resolved = false;
  let anyOpen = false;
  for (const inc of Object.values(view.incidents)) {
    if (inc.state === "resolved") {
      if (inc.root_node === id) resolved = true;
    } else {
      anyOpen = true;
      if (inc.root_node === id) openRoot = inc.verdict === "SUPPORTED_CAUSE" ? "root cause" : "anomaly";
    }
  }
  const symptom = anyOpen && view.notes.some((n) => n.node === id && n.reason.includes("symptom of"));

  let state: MetricState = scored ? "normal" : "unscored";
  if ((view.tick?.pending_nodes ?? []).includes(id)) state = "pending";
  if (z !== null && z >= view.thresholds.wiggle_z) state = "wiggle";
  if (symptom) state = "symptom";
  if (z !== null && z >= view.thresholds.alarm_z) state = "alarm";
  if (resolved && state !== "alarm") state = "resolved";
  if (openRoot) state = "root";
  if (view.focus?.nodes.includes(id)) state = "checking";

  const label = state === "root" && openRoot ? openRoot : LABEL[state];
  return { state, z, label };
}

/** An edge's status as of the latest test the stream reported, else the status the graph was served with. */
export function edgeStatus(view: RunView, edge: GraphEdge): EdgeStatus {
  return view.edges[edge.id]?.status ?? edge.status;
}

/**
 * Investigations in the order they opened: one per anomaly that has at least one step, newest last.
 * A step names its incident once one exists; the walk usually runs before the incident is filed, so an
 * investigation without a named incident takes the first incident filed after its first step and before
 * the next investigation started.
 */
export function investigations(view: RunView): { anomalyId: string; node: string; incidentId: string | null; steps: number }[] {
  const started = view.anomalies
    .map((a) => ({ anomaly: a, steps: view.steps.filter((s) => s.anomalyId === a.id) }))
    .filter((x) => x.steps.length > 0);
  const incidents = Object.values(view.incidents).sort((a, b) => a.firstSeq - b.firstSeq);
  return started.map(({ anomaly, steps }, i) => {
    const from = steps[0].seq;
    const until = started[i + 1]?.steps[0].seq ?? Infinity;
    const named = steps.find((s) => s.incidentId)?.incidentId ?? null;
    const filed = incidents.find((inc) => inc.firstSeq > from && inc.firstSeq < until)?.id ?? null;
    return { anomalyId: anomaly.id, node: anomaly.node, incidentId: named ?? filed, steps: steps.length };
  });
}

export function nodeLabel(graph: Graph | null, id: string): string {
  return graph?.nodes.find((n) => n.id === id)?.label ?? id.replace(/_/g, " ");
}
