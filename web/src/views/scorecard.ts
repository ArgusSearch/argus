// The bench scorecard (src/bench/scorecard.py `Scorecard`) shaped for the table. Pure. The numbers are the
// bench's own; this file only picks, orders and labels them, and marks misses so they cannot hide.

export interface ScenarioRow {
  agent: string;
  scenario: string;
  runs: number;
  passed: number;
  pass_at_1: number;
  k: number;
  pass_hat_k: number;
  mean_grade: number | null;
  ttd_median_h: number | null;
  false_alarms: number;
  verdicts: string[];
}

export interface AgentSummary {
  agent: string;
  runs: number;
  live_days: number;
  faults: number;
  detected: number;
  recall: number | null;
  cause_correct: number;
  cause_accuracy: number | null;
  exact: number;
  ttd_median_h: number | null;
  ttd_max_h: number | null;
  pages: number;
  true_pages: number;
  precision: number | null;
  false_alarms: number;
  false_alarms_per_day: number | null;
  quiet_false_alarms_per_day: number | null;
  innocent: number;
  innocent_handled: number;
  data_faults: number;
  data_handled: number;
  data_claims: number;
  data_precision: number | null;
  mean_grade: number | null;
  pass_at_1: number | null;
  all_verified: boolean;
  agent_seconds: number;
}

export interface Scorecard {
  created_at: string;
  git_commit: string;
  bench_commitment: string;
  seeds: number[];
  scenarios: string[];
  agents: string[];
  unavailable?: Record<string, string>;
  summaries: AgentSummary[];
  rows: ScenarioRow[];
  runs?: unknown[];
}

export function isScorecard(x: unknown): x is Scorecard {
  if (!x || typeof x !== "object") return false;
  const c = x as Partial<Scorecard>;
  return Array.isArray(c.summaries) && Array.isArray(c.rows) && Array.isArray(c.scenarios) && typeof c.bench_commitment === "string";
}

export type Tone = "good" | "warn" | "bad" | "neutral";

export interface Metric {
  key: string;
  label: string;
  hint: string;
  value: string;
  tone: Tone;
}

const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);
const num = (v: number | null, unit = "") => (v === null ? "–" : `${Number.isInteger(v) ? v : v.toFixed(2)}${unit}`);
const toneOf = (v: number | null, good = 1, warn = 0.67): Tone => (v === null ? "neutral" : v >= good ? "good" : v >= warn ? "warn" : "bad");

/** The headline measures of one agent, in the order a judge reads them. */
export function summaryMetrics(s: AgentSummary): Metric[] {
  return [
    { key: "recall", label: "Faults found", hint: `${s.detected} of ${s.faults} injected faults paged`, value: pct(s.recall), tone: toneOf(s.recall) },
    {
      key: "cause",
      label: "Right cause",
      hint: `${s.cause_correct} of ${s.faults} with the supported cause matching the hidden truth`,
      value: pct(s.cause_accuracy),
      tone: toneOf(s.cause_accuracy),
    },
    {
      key: "ttd",
      label: "Time to detect",
      hint: s.ttd_max_h === null ? "median sim hours from fault start to the first page" : `median, worst ${num(s.ttd_max_h, " h")}`,
      value: num(s.ttd_median_h, " h"),
      tone: "neutral",
    },
    {
      key: "fa",
      label: "False alarms",
      hint: `${s.false_alarms} pages that touched no fault, ${num(s.false_alarms_per_day)} per live day`,
      value: String(s.false_alarms),
      tone: s.false_alarms === 0 ? "good" : "bad",
    },
    {
      key: "expected",
      label: "Harmless changes held",
      hint: `${s.innocent_handled} of ${s.innocent} explained without a page`,
      value: s.innocent ? `${s.innocent_handled}/${s.innocent}` : "–",
      tone: s.innocent ? toneOf(s.innocent_handled / s.innocent) : "neutral",
    },
    {
      key: "data",
      label: "Data issues held",
      hint: `${s.data_handled} of ${s.data_faults} late-data faults labelled DATA_ISSUE with no page`,
      value: s.data_faults ? `${s.data_handled}/${s.data_faults}` : "–",
      tone: s.data_faults ? toneOf(s.data_handled / s.data_faults) : "neutral",
    },
    { key: "pass", label: "Runs passed", hint: `pass@1 over ${s.runs} sealed runs`, value: pct(s.pass_at_1), tone: toneOf(s.pass_at_1) },
  ];
}

export interface Cell {
  row: ScenarioRow;
  tone: Tone;
  passLabel: string;
}

export interface ScenarioLine {
  scenario: string;
  cells: Record<string, Cell | undefined>;
}

/** One line per scenario, one cell per agent; a cell is red when any of its runs failed. */
export function scenarioLines(card: Scorecard): ScenarioLine[] {
  return card.scenarios.map((scenario) => {
    const cells: Record<string, Cell | undefined> = {};
    for (const agent of card.agents) {
      const row = card.rows.find((r) => r.agent === agent && r.scenario === scenario);
      if (!row) continue;
      const tone: Tone = row.passed === row.runs ? "good" : row.passed === 0 ? "bad" : "warn";
      cells[agent] = { row, tone, passLabel: `${row.passed}/${row.runs}` };
    }
    return { scenario, cells };
  });
}

/** Rows where an agent did not pass every run: shown, never hidden. */
export function misses(card: Scorecard, agent: string): ScenarioRow[] {
  return card.rows.filter((r) => r.agent === agent && r.passed < r.runs);
}

/** "exact, exact, silent" -> [["exact", 2], ["silent", 1]] in seed order. */
export function foldLabels(labels: string[]): [string, number][] {
  const out: [string, number][] = [];
  for (const l of labels) {
    const last = out[out.length - 1];
    if (last && last[0] === l) last[1]++;
    else out.push([l, 1]);
  }
  return out;
}

export const SCENARIO_TEXT: Record<string, string> = {
  quiet: "Quiet world: nothing happens",
  s1: "S1 · PayCo outage + release red herring",
  s2: "S2 · planned FR budget increase (harmless)",
  s3: "S3 · orders loader stalls (late data)",
  s4: "S4 · ad pacer 1.7 burns budgets by 10:00",
  s5: "S5 · market-wide demand drop + checkout config fault",
};

export const AGENT_TEXT: Record<string, string> = {
  argus: "Argus",
  "argus-stage1": "Stage 1 only",
  threshold: "Threshold baseline",
};

/** Argus first, then what it is measured against: its own Stage-1 fallback, then the BI-style threshold alert. */
const AGENT_ORDER = ["argus", "argus-stage1", "threshold"];

/** Every agent's summary in reading order: Argus, then its references; agents the order does not know go last. */
export function orderedSummaries(card: Scorecard): AgentSummary[] {
  const rank = (a: string) => (AGENT_ORDER.includes(a) ? AGENT_ORDER.indexOf(a) : AGENT_ORDER.length);
  return [...card.summaries].sort((a, b) => rank(a.agent) - rank(b.agent));
}

export interface HeadlineRow {
  key: string;
  label: string;
  hint: string;
  /** One cell per agent in `orderedSummaries` order. */
  cells: { agent: string; value: string; tone: Tone }[];
}

/**
 * The dashboard's short table: the chosen measures, one column per agent. Only Argus keeps its tones; a
 * reference agent's cells are neutral, so a baseline's or Stage 1's miss never reads as a miss of Argus.
 */
export function headlineRows(card: Scorecard, keys: string[]): HeadlineRow[] {
  const agents = orderedSummaries(card).map((s) => ({ agent: s.agent, metrics: summaryMetrics(s) }));
  const first = agents[0]?.metrics ?? [];
  return keys.flatMap((key) => {
    const m = first.find((x) => x.key === key);
    if (!m) return [];
    const cells = agents.map(({ agent, metrics }) => {
      const cell = metrics.find((x) => x.key === key);
      return { agent, value: cell?.value ?? "–", tone: agent === "argus" && cell ? cell.tone : ("neutral" as Tone) };
    });
    return [{ key, label: m.label, hint: m.hint, cells }];
  });
}
