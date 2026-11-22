// Pure reading of a placement for the screen: the verdict in words, the routes into the new node (its parents),
// the formulas it feeds, its breakdowns and the reasoning. Every number comes from the API's test results.

import type { EdgeTestResult } from "../lib/types";
import type { CandidateView, PlacedAs, PlacementResult } from "./types";

export type Tone = "good" | "watch" | "bad";

export interface Route {
  id: string;
  sources: string[];
  /** VALID, PROBATION, ... for an edge that entered the graph; ALTERNATIVE for an equally good one kept aside */
  status: string;
  reads: string;
  evidence: string;
}

export interface Feed {
  id: string;
  target: string;
  other: string[];
  reads: string;
  status: string;
  evidence: string;
}

export interface PlacementView {
  name: string;
  label: string;
  verdict: PlacedAs;
  tone: Tone;
  kind: string;
  headline: string;
  routes: Route[];
  feeds: Feed[];
  dims: string[];
  causes: string[];
  reasons: string[];
  tested: number;
  receipts: number;
}

export const VERDICT_TONE: Record<PlacedAs, Tone> = {
  EXACT: "good",
  NEW_DIMENSION: "good",
  ALIAS: "good",
  AMBIGUOUS: "watch",
  REJECTED: "bad",
};

const VERDICT_LABEL: Record<PlacedAs, string> = {
  EXACT: "exact",
  NEW_DIMENSION: "new dimension",
  ALIAS: "alias",
  AMBIGUOUS: "ambiguous",
  REJECTED: "rejected",
};

export function verdictLabel(v: PlacedAs): string {
  return VERDICT_LABEL[v];
}

/** The deciding number of a test in words, e.g. "residual 0.00 % over 672 h". */
export function evidenceOf(result: EdgeTestResult | null): string {
  if (!result) return "not tested here";
  if (result.median_rel !== null) return `residual ${(result.median_rel * 100).toFixed(2)} % over ${result.hours} h`;
  if (result.max_rel_err !== null) return `children sum within ${(result.max_rel_err * 100).toFixed(2)} % over ${result.hours} h`;
  return result.note || (result.passed ? "passed" : "failed");
}

const ACRONYMS = new Set(["ctr", "cpc", "cpa", "cpm", "roas", "cvr", "aov", "gmv", "id"]);

/** "cost_per_impression" -> "Cost per impression", "ctr" -> "CTR", "attributed_gmv" -> "Attributed GMV". */
export function labelOf(id: string): string {
  const words = id.split("_").map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w));
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const inGraph = (c: CandidateView) => c.lifecycle === "accepted";

function routes(p: PlacementResult, id: string): Route[] {
  return p.candidates
    .filter((c) => c.edge.kind === "formula" && c.edge.target === id && (c.lifecycle === "accepted" || c.lifecycle === "tested"))
    .map((c) => ({
      id: c.edge.id,
      sources: c.edge.sources,
      status: c.lifecycle === "tested" ? "ALTERNATIVE" : c.edge.status,
      reads: c.reads,
      evidence: evidenceOf(c.result),
    }))
    .sort((a, b) => Number(a.status === "ALTERNATIVE") - Number(b.status === "ALTERNATIVE"));
}

function feeds(p: PlacementResult, id: string): Feed[] {
  return p.candidates
    .filter((c) => c.edge.kind === "formula" && c.edge.sources.includes(id) && inGraph(c))
    .map((c) => ({
      id: c.edge.id,
      target: c.edge.target,
      other: c.edge.sources.filter((s) => s !== id),
      reads: c.reads,
      status: c.edge.status,
      evidence: evidenceOf(c.result),
    }));
}

const times = (xs: string[]) => xs.map(labelOf).join(" × ");

function headline(p: PlacementResult, r: Route[]): string {
  const chosen = r.find((x) => x.status !== "ALTERNATIVE");
  switch (p.placed_as) {
    case "EXACT":
      return chosen
        ? `${labelOf(p.metric.name)} = ${times(chosen.sources)}, proven on the data (${chosen.evidence}).`
        : `${labelOf(p.metric.name)} joins the graph: ${p.definition}.`;
    case "AMBIGUOUS": {
      const alt = r.filter((x) => x.status === "ALTERNATIVE");
      if (chosen && alt.length)
        return `Two parents fit equally well: ${times(chosen.sources)} or ${alt.map((a) => times(a.sources)).join(" or ")}. Argus keeps the first on probation at half weight and the other as an alternative until the evidence decides.`;
      return `Placed on probation: ${p.certificate.uncertain[0] ?? p.summary}.`;
    }
    case "REJECTED":
      if (p.repair) return `Not placed: the join counts rows ${p.repair.factor.toFixed(2)} times over. A repaired query is attached.`;
      return `Not placed: ${p.summary}.`;
    default:
      return p.summary;
  }
}

function reasons(p: PlacementResult): string[] {
  if (p.placed_as === "REJECTED") {
    const head = p.summary.split(" (")[0];
    return [head, ...p.certificate.tried.filter((t) => t.startsWith("fan-out guard"))];
  }
  const out = [p.definition ? `definition check: ${p.definition}` : ""];
  out.push(...p.certificate.uncertain.filter((u) => u.startsWith("ambiguous")));
  return out.filter(Boolean);
}

export function placementView(p: PlacementResult): PlacementView {
  const id = p.node?.id ?? p.metric.name;
  const r = routes(p, id);
  const verdict = p.placed_as;
  return {
    name: p.metric.name,
    label: p.node?.label ?? labelOf(p.metric.name),
    verdict,
    tone: VERDICT_TONE[verdict],
    kind: verdict === "REJECTED" ? "Metric rejected" : verdict === "ALIAS" || verdict === "NEW_DIMENSION" ? "Metric already known" : "New metric placed",
    headline: headline(p, r),
    routes: r,
    feeds: feeds(p, id),
    dims: p.candidates.filter((c) => c.edge.kind === "breakdown" && inGraph(c)).map((c) => c.edge.dim ?? ""),
    causes: p.candidates.filter((c) => c.edge.kind === "cause" && inGraph(c)).map((c) => c.reads),
    reasons: reasons(p),
    tested: p.candidates.filter((c) => c.result !== null).length,
    receipts: p.receipts.length,
  };
}

/** Node ids the placements added to the graph, newest last. */
export function placedNodes(placements: PlacementResult[]): string[] {
  return placements.flatMap((p) => (p.node ? [p.node.id] : []));
}

/** The next metric of the pack that is not placed yet (null when the whole pack is in). */
export function nextOfPack<T extends { name: string }>(state: { placements: PlacementResult[]; recorded: T[] }): T | null {
  const done = new Set(state.placements.map((p) => p.metric.name));
  return state.recorded.find((m) => !done.has(m.name)) ?? null;
}
