// The blind challenge as the bench lane records it: three C5 `challenge_state` payloads (committed,
// running, revealed). Shapes follow src/bench/blind.py and src/bench/sealed.py on fm/argus-bench.

import { segmentLabel } from "../lib/format";

export type ChallengePhase = "committed" | "running" | "revealed";

export interface GradeEvent {
  event_id: string;
  kind: string;
  expected: string;
  grade: number;
  label: string;
  claim: string | null;
  claimed: string | null;
  ttd_hours: number | null;
}

export interface Grade {
  case: string;
  scenario: string;
  seed: number;
  agent: string;
  commitment: string;
  verified: boolean;
  live_days: number;
  events: GradeEvent[];
  claims: number;
  pages: number;
  false_alarms: unknown[];
  data_claims: number;
  true_data_claims: number;
  agent_seconds: number;
  error: string | null;
}

export interface Reveal {
  scenario: string;
  seed: number;
  nonce: string;
  payload: string;
  verified: boolean;
  grade: Grade;
}

export interface ChallengeState {
  state: ChallengePhase;
  commitment: string;
  reveal: Reveal | null;
}

export interface TruthEvent {
  event_id: string;
  kind: string;
  description: string;
  scenario: string;
  root_node: string | null;
  segment: Record<string, string>;
  start_ts: string;
  end_ts: string | null;
  expected: { verdict?: string; root_node?: string; segment?: Record<string, string>; evidence?: string; ruled_out?: string[] };
}

export interface Truth {
  events: TruthEvent[];
  world_params: Record<string, string>;
}

export interface ArgusClaim {
  id: string;
  title: string;
  verdict: string;
  state: string;
  root_node: string;
  segment: Record<string, string>;
  evidence?: string;
  opened_at: string;
  resolved_at: string | null;
  ruled_out: { ref: string; reason: string; hypothesis: string }[];
}

/** Parse challenge.jsonl, keeping only well-formed challenge_state payloads, in file order. */
export function parseChallenge(jsonl: string): ChallengeState[] {
  const out: ChallengeState[] = [];
  for (const line of jsonl.split("\n")) {
    if (!line.trim()) continue;
    const row = JSON.parse(line) as Partial<ChallengeState>;
    if ((row.state === "committed" || row.state === "running" || row.state === "revealed") && typeof row.commitment === "string") {
      out.push({ state: row.state, commitment: row.commitment, reveal: row.reveal ?? null });
    }
  }
  return out;
}

/** The hidden truth inside a reveal's payload (canonical JSON), or null when it does not parse. */
export function truthOf(reveal: Reveal): Truth | null {
  try {
    const t = JSON.parse(reveal.payload) as Truth;
    return Array.isArray(t.events) ? t : null;
  } catch {
    return null;
  }
}

const SCENARIO_NAMES: Record<string, string> = {
  s1: "S1 · payment outage with a red-herring release",
  s2: "S2 · planned budget increase",
  s3: "S3 · orders loader stall",
  s4: "S4 · ad pacer rollout",
  quiet: "Quiet world · nothing happens",
};

export function scenarioName(id: string): string {
  return SCENARIO_NAMES[id] ?? id;
}

/** Readable verdict labels without touching the API values. */
const VERDICTS: Record<string, string> = {
  SUPPORTED_CAUSE: "Supported cause",
  HYPOTHESIS: "Hypothesis",
  EXPECTED: "Expected",
  DATA_ISSUE: "Data issue",
  UNEXPLAINED: "Unexplained",
};

export function verdictLabel(v: string | null | undefined): string {
  if (!v) return "no claim";
  return VERDICTS[v] ?? v.toLowerCase().replace(/_/g, " ");
}

export interface Row {
  event: string;
  kind: string;
  truth: string;
  argus: string;
  label: string;
  grade: number;
  ttd: string;
  hit: boolean;
}

/** One line per hidden event: what the truth expected next to what Argus claimed and how it was graded. */
export function compareRows(reveal: Reveal): Row[] {
  const truth = truthOf(reveal);
  return reveal.grade.events.map((g) => {
    const t = truth?.events.find((e) => e.event_id === g.event_id);
    const where = t?.expected.segment ? ` on ${segmentLabel(t.expected.segment)}` : "";
    return {
      event: t?.description ?? g.event_id,
      kind: g.kind,
      truth: `${verdictLabel(g.expected)}${where}`,
      argus: g.claimed ? `${verdictLabel(g.claimed)}${g.claim ? ` (${g.claim})` : ""}` : "no claim",
      label: g.label,
      grade: g.grade,
      ttd: g.ttd_hours === null ? "–" : `${g.ttd_hours} h`,
      hit: g.claimed === g.expected,
    };
  });
}

/**
 * PASS exactly as RunGrade.passed in src/bench/grade.py (PASS_GRADE = 3).
 * shortcut: mirrors the bench rule because the recorded grade has no `passed` field; read it from the API once
 * the challenge routes send it (see docs/demo/issues/api-blind-challenge-routes.md).
 */
export function passed(grade: Grade): boolean {
  return grade.verified && grade.error === null && grade.false_alarms.length === 0 && grade.events.every((e) => e.grade >= 3);
}
