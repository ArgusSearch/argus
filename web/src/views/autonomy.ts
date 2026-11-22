// Y6 · What Argus did on its own so far: counts the reducer already folded, nothing new is measured here.

import type { RunView } from "../lib/store";
import { investigations } from "./model";

export interface AutonomyCount {
  key: string;
  label: string;
  value: number;
}

export function autonomyCounts(view: RunView): AutonomyCount[] {
  return [
    { key: "hours", label: view.ticks === 1 ? "hour watched" : "hours watched", value: view.ticks },
    { key: "edges", label: view.edgeChanges.length === 1 ? "edge test" : "edge tests", value: view.edgeChanges.length },
    { key: "anomalies", label: view.anomalies.length === 1 ? "anomaly" : "anomalies", value: view.anomalies.length },
    { key: "investigations", label: "investigated", value: investigations(view).length },
    { key: "incidents", label: Object.keys(view.incidents).length === 1 ? "incident" : "incidents", value: Object.keys(view.incidents).length },
    { key: "notes", label: "didn't wake you", value: view.notes.length },
    { key: "human", label: "human actions", value: 0 },
  ];
}
