// What the dashboard's affected-path card follows. The card shows the scene's preview, which frames the affected
// path of the latest anomaly (scene/model.ts incidentPath), so the card follows the same anomaly by the same
// rules as the scene's phases: it appears with the anomaly, stays through the investigation and the open
// incident, and leaves when that incident resolves. A walk that closed without an incident (a planned change,
// late data) is no incident, so the card leaves with its verdict.

import type { IncidentView, RunView } from "../../lib/store";

export interface PathSubject {
  /** the anomalous metric the path starts at */
  node: string;
  /** where its walk stands: just detected, under investigation, or decided with an open incident */
  phase: "anomaly" | "investigating" | "verdict";
  /** the incident the walk filed, once there is one */
  incident: IncidentView | null;
}

export function affectedPath(view: RunView): PathSubject | null {
  const anomaly = view.anomalies[view.anomalies.length - 1];
  if (!anomaly) return null;
  const steps = view.steps.filter((s) => s.anomalyId === anomaly.id);
  const filed = new Set(steps.map((s) => s.incidentId).filter((id): id is string => id !== null));
  const incident = Object.values(view.incidents).find((inc) => filed.has(inc.id) || inc.root_node === anomaly.node) ?? null;
  if (incident?.state === "resolved") return null;
  const decided = steps.some((s) => s.step.kind === "verdict");
  if (decided && !incident) return null;
  return { node: anomaly.node, phase: decided ? "verdict" : steps.length ? "investigating" : "anomaly", incident };
}
