import type { EvidenceRef, Incident } from "../../lib/types";
import { STATE } from "./plain";

interface TimelineEntry {
  key: string;
  at: string;
  label: string;
  detail: string;
  kind: "state" | "evidence";
}

/** Combine the API's incident transitions with the underlying log entries that were checked. */
export function incidentTimeline(incident: Incident): TimelineEntry[] {
  const events = new Map<string, TimelineEntry>();
  const root = incident.findings.root?.evidence;
  const add = (event: EvidenceRef, label: string) => {
    const key = `log:${event.log}:${event.ref}`;
    if (events.has(key)) return;
    events.set(key, { key, at: event.ts, label, detail: event.description, kind: "evidence" });
  };
  if (root) add(root, incident.verdict === "SUPPORTED_CAUSE" ? "Cause logged" : "Possible cause logged");
  for (const ruled of incident.findings.ruled_out) {
    if (ruled.evidence) add(ruled.evidence, ruled.result === "refuted" ? "Ruled-out change" : "Change checked");
  }

  const states = incident.history.map(({ from_state, to_state, sim_ts }, index): TimelineEntry => ({
    key: `state:${index}`,
    at: sim_ts,
    label: to_state === "open" && from_state !== null ? "Reopened" : STATE[to_state].label,
    detail: STATE[to_state].help,
    kind: "state",
  }));
  return [...events.values(), ...states].sort((a, b) => a.at.localeCompare(b.at));
}
