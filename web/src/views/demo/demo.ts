// Demo mode, pure parts: the URL options and the caption for the moment the run is in.
//
//   ?demo=1            hands-off mode for the video (Esc leaves it)
//   &speed=2           replay speed (1, 2, 4 or 8; default 2)
//   &captions=1        one caption line per beat
//   &hold=12           seconds the incident report stays open before the page returns to the graph
//   &end=report        open the morning report when the run is complete

import { wherePhrase } from "../../fx/workspace/plain";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { breadcrumb, chapterOf, spreadOf, suspects, verdictOf } from "../investigation";
import { investigations, nodeLabel } from "../model";

export interface DemoOptions {
  demo: boolean;
  speed: number;
  captions: boolean;
  hold: number;
  endOnReport: boolean;
}

const SPEEDS = [1, 2, 4, 8];

export function demoOptions(search: string): DemoOptions {
  const q = new URLSearchParams(search);
  const on = (key: string) => ["1", "true", "yes", "on"].includes((q.get(key) ?? "").toLowerCase());
  const speed = Number(q.get("speed"));
  const hold = Number(q.get("hold"));
  return {
    demo: on("demo"),
    speed: SPEEDS.includes(speed) ? speed : 2,
    captions: on("captions"),
    hold: Number.isFinite(hold) && hold >= 3 && hold <= 120 ? hold : 12,
    endOnReport: (q.get("end") ?? "").toLowerCase() === "report",
  };
}

/** The URL without the demo options, for leaving demo mode in place. */
export function withoutDemo(href: string): string {
  const url = new URL(href);
  for (const key of ["demo", "speed", "captions", "hold", "end"]) url.searchParams.delete(key);
  return url.pathname + (url.search ? url.search : "") + url.hash;
}

export interface Beat {
  /** stable id; the click path in docs/demo/click-path.md refers to these */
  id: "watching" | "anomaly" | "checks" | "localised" | "suspects" | "verdict" | "monitoring" | "resolved" | "held";
  text: string;
}

const VERDICT_TEXT: Record<string, string> = {
  SUPPORTED_CAUSE: "supported cause",
  HYPOTHESIS: "a hypothesis",
  EXPECTED: "expected",
  DATA_ISSUE: "a data issue",
  UNEXPLAINED: "unexplained",
};

/** The caption for the moment the run is in. Captions name things; they never state a number. */
export function beatFor(view: RunView, graph: Graph | null): Beat {
  const metrics = graph?.nodes.length;
  const latestFeed = view.feed[view.feed.length - 1];
  const inv = investigations(view);
  const current = inv[inv.length - 1];
  const incident = current?.incidentId ? view.incidents[current.incidentId] : undefined;
  const steps = current ? view.steps.filter((s) => s.anomalyId === current.anomalyId) : [];

  if (incident?.state === "resolved") return { id: "resolved", text: "Recovered. After three normal hours Argus closes the incident by itself." };
  if (incident?.state === "monitoring") return { id: "monitoring", text: "Back inside its band. Argus keeps watching before it closes the incident." };
  if (incident && incident.verdict !== "UNEXPLAINED") {
    const where = Object.keys(incident.segment).length ? incident.segment : spreadOf(suspects(steps))?.scope ?? {};
    return {
      id: "verdict",
      text: `Verdict for ${wherePhrase(where)}: ${VERDICT_TEXT[incident.verdict]}. The incident shows its cost, ruled-out causes and receipts.`,
    };
  }
  if (current) {
    const verdict = verdictOf(steps.map((s) => s.step));
    if (!incident && verdict === "EXPECTED") {
      return { id: "held", text: "It looked like an anomaly, but it was planned and delivered as planned. Argus did not wake anyone." };
    }
    if (!incident && verdict === "DATA_ISSUE") {
      return { id: "held", text: "The data is late, not the business: Argus holds the alert and re-checks after the backfill." };
    }
    const last = steps[steps.length - 1];
    const tested = suspects(steps);
    const out = tested.filter((s) => !s.kept);
    if (out.length) return { id: "suspects", text: `Ruled out by a holdout: ${out[out.length - 1].description}. The rest of its scope is normal.` };
    if (tested.length) return { id: "suspects", text: "Each suspect from the logs is tested against the part of its scope that did not break." };
    const crumbs = breadcrumb(
      steps.map((s) => s.step),
      current.node,
    ).crumbs;
    if (crumbs.length) return { id: "localised", text: `Localised: ${crumbs.map((c) => c.value).join(" · ")}. Now: what changed at that moment?` };
    if (last && ["data", "plan"].includes(chapterOf(last.step))) {
      return { id: "checks", text: "First the boring checks: is the data complete, do the formulas hold, was anything planned?" };
    }
    if (last) return { id: "checks", text: `Splitting ${nodeLabel(graph, current.node)} along its formula to find where the change sits.` };
  }
  const anomaly = view.anomalies[view.anomalies.length - 1];
  if (anomaly && !current) return { id: "anomaly", text: `${nodeLabel(graph, anomaly.node)} left its expected band. Argus opens an investigation, no one asked.` };
  if (latestFeed?.kind === "note" && latestFeed.note.kind !== "suppressed") {
    return {
      id: "held",
      text:
        latestFeed.note.kind === "data_issue"
          ? "The data is late, not the business: Argus holds the alert and re-checks after the backfill."
          : "A planned change moved the numbers. Argus noticed, checked the plan, and did not wake anyone.",
    };
  }
  return {
    id: "watching",
    text: `Watching ${metrics ? `${metrics} metrics` : "every metric"} each simulated hour. No one is at the keyboard.`,
  };
}

/** True once any step of the investigation exists: the moment demo mode switches to the investigation view. */
export function investigationStarted(view: RunView): boolean {
  return view.steps.length > 0;
}

/** Investigations that ended without an incident (EXPECTED, DATA_ISSUE): demo mode returns to the graph. */
export function closedWithoutIncident(view: RunView): string[] {
  return investigations(view)
    .filter((i) => !i.incidentId && verdictOf(view.steps.filter((s) => s.anomalyId === i.anomalyId).map((s) => s.step)) !== null)
    .map((i) => i.anomalyId);
}

/** Incidents that reached a verdict other than UNEXPLAINED, in the order they did. */
export function decidedIncidents(view: RunView): string[] {
  return Object.values(view.incidents)
    .filter((i) => i.verdict !== "UNEXPLAINED")
    .sort((a, b) => a.firstSeq - b.firstSeq)
    .map((i) => i.id);
}

