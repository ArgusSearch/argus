// Pure helpers that turn the investigation steps of one anomaly into a story a judge can read top to bottom.

import { isRuledOut, type StepView } from "../lib/store";
import type { EvidenceRef, Segment, TrailStep } from "../lib/types";

/** The question each step of the playbook answers, in plain words. Unknown kinds fall back to their name. */
const QUESTION: Record<string, string> = {
  freshness: "Is the data complete?",
  identities: "Do the formulas still hold?",
  calendar: "Was this planned?",
  decompose: "Which factor moved?",
  segment: "Where exactly is it?",
  events: "What changed at that moment?",
  holdout: "Does this suspect explain it?",
  impact: "What does it cost?",
  verdict: "Verdict",
  skeptic: "Can the conclusion be broken?",
};

export function stepQuestion(step: TrailStep): string {
  if (step.kind === "segment" && step.tool === "get_series") return "When did it start?";
  if (step.kind === "impact" && step.tool === "counterfactual_impact") return "How much money is it?";
  if (step.kind === "impact") return "Which factor carries the change?";
  return QUESTION[step.kind] ?? step.kind.replace(/_/g, " ");
}

export type Chapter = "data" | "plan" | "where" | "why" | "cost" | "verdict" | "other";

const CHAPTER: Record<string, Chapter> = {
  freshness: "data",
  identities: "data",
  calendar: "plan",
  decompose: "where",
  segment: "where",
  events: "why",
  holdout: "why",
  impact: "cost",
  verdict: "verdict",
};

export const CHAPTER_TITLE: Record<Chapter, string> = {
  data: "1 · Trust the data first",
  plan: "2 · Rule out the calendar",
  where: "3 · Localise",
  why: "4 · Test the suspects",
  cost: "5 · Quantify",
  verdict: "6 · Decide",
  other: "More checks",
};

export function chapterOf(step: TrailStep): Chapter {
  return CHAPTER[step.kind] ?? "other";
}

/** Consecutive steps of the same chapter, in stream order. */
export function chapters(steps: StepView[]): { chapter: Chapter; steps: StepView[] }[] {
  const out: { chapter: Chapter; steps: StepView[] }[] = [];
  for (const s of steps) {
    const chapter = chapterOf(s.step);
    const last = out[out.length - 1];
    if (last && last.chapter === chapter) last.steps.push(s);
    else out.push({ chapter, steps: [s] });
  }
  return out;
}

interface PathCell {
  segment: Segment;
  ep?: number;
  volume_share?: number;
  rel_change?: number;
}

export interface Crumb {
  dim: string;
  value: string;
}

/**
 * The root-cause path through the graph: the anomalous node, then each dimension value the segment search
 * added, in the order it added them (`step.data.path`).
 */
export function breadcrumb(steps: TrailStep[], node: string | null): { node: string | null; crumbs: Crumb[] } {
  const seg = steps.find((s) => s.kind === "segment" && Array.isArray((s.data as { path?: unknown }).path));
  const path = ((seg?.data as { path?: PathCell[] } | undefined)?.path ?? []).filter((c) => c && typeof c.segment === "object");
  const crumbs: Crumb[] = [];
  let previous: Segment = {};
  for (const cell of path) {
    for (const [dim, value] of Object.entries(cell.segment)) {
      if (previous[dim] !== value) crumbs.push({ dim, value });
    }
    previous = cell.segment;
  }
  return { node, crumbs };
}

export interface Suspect {
  seq: number;
  ref: string;
  description: string;
  log: string;
  ts: string;
  scope: Record<string, string[]>;
  kept: boolean;
  hypothesis: string | null;
  prediction: string | null;
  reason: string;
  decision: string;
  receipts: string[];
}

/** Every candidate cause the holdout step tested, with what happened to it. */
export function suspects(steps: StepView[]): Suspect[] {
  const out: Suspect[] = [];
  for (const s of steps) {
    if (s.step.kind !== "holdout") continue;
    const e = (s.step.data as { event?: EvidenceRef }).event;
    if (!e) continue;
    out.push({
      seq: s.seq,
      ref: e.ref,
      description: e.description,
      log: e.log,
      ts: e.ts,
      scope: e.scope ?? {},
      kept: !isRuledOut(s.step.decision),
      hypothesis: s.step.hypothesis,
      prediction: s.step.prediction,
      reason: s.step.result,
      decision: s.step.decision,
      receipts: s.step.receipts,
    });
  }
  return out;
}

/** "platform android, all countries" from an event scope; an empty scope means everyone. */
export function scopeLabel(scope: Record<string, string[]>): string {
  const parts = Object.entries(scope).map(([dim, values]) => `${dim} ${values.join(", ")}`);
  return parts.length ? parts.join(" · ") : "everyone";
}

/** The verdict step's result, once the investigation reached it. */
export function verdictOf(steps: TrailStep[]): string | null {
  return steps.find((s) => s.kind === "verdict")?.result ?? null;
}
