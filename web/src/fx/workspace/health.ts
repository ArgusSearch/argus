// The overview's numbers: the shop health score with its four checks, the KPI tiles and the week's tasks. Pure
// functions over the folded run (and the incidents the API serves); every value is a count of things the stream
// reported, never a weight or a model output, so the score can be explained in one sentence.

import { eur } from "../../lib/format";
import type { RunView } from "../../lib/store";
import type { Graph, Incident } from "../../lib/types";
import { metricStatus } from "../../views/model";
import { metricName, storyHeadline, type Tone } from "./plain";

export interface Check {
  key: "data" | "metrics" | "formulas" | "incidents";
  label: string;
  passed: number;
  total: number;
  /** passed / total, 1 when there is nothing to check */
  share: number;
  /** "4 of 4 sources delivered" */
  detail: string;
  tone: Tone;
}

export interface Health {
  /** 0 to 100, the plain average of the checks; null before the first scored hour */
  score: number | null;
  checks: Check[];
  tone: Tone;
}

const ratio = (passed: number, total: number) => (total ? passed / total : 1);
const toneOf = (share: number): Tone => (share >= 0.999 ? "ok" : share >= 0.75 ? "watch" : "alarm");

function check(key: Check["key"], label: string, passed: number, total: number, detail: string): Check {
  const share = ratio(passed, total);
  return { key, label, passed, total, share, detail, tone: toneOf(share) };
}

/** States that count as "in its usual range" for the health score; unscored metrics do not count at all. */
const NORMAL = new Set(["normal", "wiggle", "resolved"]);
const COUNTED = new Set(["normal", "wiggle", "resolved", "alarm", "root", "symptom", "checking"]);

export function keyMetrics(graph: Graph | null): string[] {
  return (graph?.nodes ?? []).filter((n) => n.north_star).map((n) => n.id);
}

export function health(view: RunView, graph: Graph | null): Health {
  const tables = view.tick?.freshness ?? [];
  const onTime = tables.filter((t) => t.status === "ok").length;
  const states = keyMetrics(graph).map((id) => metricStatus(view, id).state);
  const counted = states.filter((s) => COUNTED.has(s));
  const normal = counted.filter((s) => NORMAL.has(s)).length;
  const tested = Object.values(view.edges);
  const holding = tested.filter((e) => e.status !== "BROKEN").length;
  const incidents = Object.values(view.incidents);
  const closed = incidents.filter((i) => i.state === "resolved").length;
  const checks = [
    check("data", "Data delivered", onTime, tables.length, tables.length ? `${onTime} of ${tables.length} sources on time` : "waiting for data"),
    check("metrics", "Key metrics normal", normal, counted.length, counted.length ? `${normal} of ${counted.length} in their usual range` : "not checked yet"),
    check("formulas", "Formulas hold", holding, tested.length, tested.length ? `${holding} of ${tested.length} formula checks pass` : "first check after day one"),
    check("incidents", "Incidents closed", closed, incidents.length, incidents.length ? `${closed} of ${incidents.length} closed` : "no incidents"),
  ];
  if (!view.tick) return { score: null, checks, tone: "muted" };
  const score = Math.round((100 * checks.reduce((sum, c) => sum + c.share, 0)) / checks.length);
  return { score, checks, tone: score >= 100 ? "ok" : score >= 75 ? "watch" : "alarm" };
}

export interface Tile {
  key: string;
  label: string;
  value: string;
  /** the value as a number, for the count-up; `value` is its final text */
  amount: number;
  /** format the amount as euros (else as a whole number) */
  money?: boolean;
  /** the unit or the count the value is out of, shown small next to it */
  unit?: string;
  /** what changed, in words */
  change: string;
  tone: Tone;
  /** one value per scored hour, oldest first; empty for no chart */
  series: number[];
  /** the glossary term behind the tile */
  term?: string;
  /** the tooltip: what the tile counts, in one sentence */
  hint: string;
}

/** The five tiles of the overview's header row. */
export function tiles(view: RunView, graph: Graph | null): Tile[] {
  const incidents = Object.values(view.incidents);
  const open = incidents.filter((i) => i.state !== "resolved");
  const lost = incidents.reduce((sum, i) => sum + Math.abs(i.severity_eur), 0);
  const stillOpen = open.reduce((sum, i) => sum + Math.abs(i.severity_eur), 0);
  const { alarm_z: alarm, wiggle_z: wiggle } = view.thresholds;
  const hours = view.hours;
  const metrics = keyMetrics(graph);
  const states = metrics.map((id) => ({ id, state: metricStatus(view, id).state }));
  const off = states.filter((s) => ["alarm", "root", "symptom", "checking"].includes(s.state));
  const scored = states.filter((s) => COUNTED.has(s.state)).length;

  return [
    {
      key: "cost",
      label: "Cost of incidents",
      value: eur(lost),
      amount: lost,
      money: true,
      change: open.length ? `${eur(stillOpen)} still open` : lost ? "stopped: every incident closed" : "nothing lost",
      tone: open.length ? "alarm" : "ok",
      series: hours.map((h) => h.eur),
      hint: "Lost revenue Argus measured against the usual level, summed over every incident of the run.",
    },
    {
      key: "open",
      label: "Open incidents",
      value: String(open.length),
      amount: open.length,
      change: incidents.length ? `${incidents.length - open.length} of ${incidents.length} resolved this week` : "none this week",
      tone: open.length ? "alarm" : "ok",
      series: hours.map((h) => h.open),
      hint: "Incidents Argus filed and has not closed yet. It closes one after three normal hours in a row.",
    },
    {
      key: "metrics",
      label: "Key metrics normal",
      value: String(scored - off.length),
      amount: scored - off.length,
      unit: `of ${scored}`,
      change: off.length ? `${off.map((s) => metricName(graph, s.id)).join(", ")} off usual` : "all in their usual range",
      tone: off.length ? "alarm" : "ok",
      series: hours.map((h) => h.z.filter((z) => z < alarm).length),
      term: "|z|",
      hint: "Key metrics below the alarm threshold this hour, each compared with the same hour of the last four weeks.",
    },
    {
      key: "noise",
      label: "Small moves ignored",
      value: String(view.wiggles),
      amount: view.wiggles,
      change: `${view.notes.length} alert${view.notes.length === 1 ? "" : "s"} held back on purpose`,
      tone: "ok",
      series: hours.map((h) => h.z.filter((z) => z >= wiggle && z < alarm).length),
      term: "Wiggle",
      hint: "Moves big enough to notice but below the alarm threshold: logged, never paged.",
    },
    {
      key: "human",
      label: "Human actions needed",
      value: "0",
      amount: 0,
      unit: `in ${view.ticks} h`,
      change: "detected, explained and closed alone",
      tone: "ok",
      series: [],
      hint: "Argus detects, localises, rules out and closes without a person. Only an action on the business waits for your approval.",
    },
  ];
}

export interface Task {
  id: string;
  headline: string;
  /** euros the incident cost (positive) */
  eur: number;
  /** the findings' suggested action; empty when only the agent proposed one */
  action: string;
  needsApproval: boolean;
  state: Incident["state"];
  verdict: Incident["verdict"];
}

/**
 * This week's tasks: every incident with a proposed action (in its findings, or from the agent: `proposed`), open
 * ones first, then the most expensive.
 */
export function tasks(incidents: Incident[], graph: Graph | null, proposed: ReadonlySet<string> = new Set()): Task[] {
  return incidents
    .filter((i) => i.findings.suggested_action || proposed.has(i.id))
    .map((i) => {
      const f = i.findings;
      const root = f.root;
      return {
        id: i.id,
        headline: storyHeadline(graph, root?.node ?? i.root_node, root?.change_pct.value ?? null, root?.segment ?? i.segment),
        eur: Math.abs(i.severity_eur),
        action: f.suggested_action ? f.suggested_action.text.replace(/\.?$/, ".") : "",
        needsApproval: f.suggested_action?.needs_approval ?? true,
        state: i.state,
        verdict: i.verdict,
      };
    })
    .sort((a, b) => Number(a.state === "resolved") - Number(b.state === "resolved") || b.eur - a.eur);
}
