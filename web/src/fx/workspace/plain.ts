// Plain words for the first level of the workspace. Internal terms (|z|, LMDI, edge tests, series-hours, holdout)
// stay out of headings, tiles and buttons; they live in the glossary and in the tooltips that open from it.
// Pure: no React, no DOM, so the wording is tested once and reused by every page.

import type { Graph, Incident, IncidentState, Segment, Verdict } from "../../lib/types";
import { monitoringText } from "../../lib/format";

/** Where something happens: a segment's single values, or a scope's lists (country: ["DE", "FR"]). */
export type Where = Segment | Record<string, string | string[]>;

/**
 * Where an incident happens, for its headline: the root segment, else the incident's, else the scope of the logged
 * change that caused it (S4: the pacer change scoped to DE and FR on a shop-wide ratio), so the words never say
 * "the whole shop" while the action targets two countries.
 */
export function incidentWhere(incident: Pick<Incident, "segment" | "findings">): Where {
  const root = incident.findings.root;
  if (root && Object.keys(root.segment).length) return root.segment;
  if (Object.keys(incident.segment).length) return incident.segment;
  const scope = root?.evidence?.scope;
  return scope && Object.keys(scope).length ? scope : {};
}

export type Tone = "ok" | "watch" | "alarm" | "probe" | "muted";

/** Short names for the metrics the dashboard lists; the graph's own label is the fallback. */
const METRIC: Record<string, string> = {
  sessions: "Visits",
  orders: "Orders",
  gmv: "Revenue (GMV)",
  payment_success_rate: "Payment success",
  cvr: "Conversion",
  ad_spend: "Ad spend",
  cpa: "Cost per order",
  aov: "Order value",
  impressions_per_session: "Ads per visit",
  pacing_ratio: "Ad budget pacing",
};

export function metricName(graph: Graph | null, id: string): string {
  return METRIC[id] ?? graph?.nodes.find((n) => n.id === id)?.label ?? id.replace(/_/g, " ");
}

/** What each verdict means to the person reading the incident. */
export const VERDICT: Record<Verdict, { label: string; tone: Tone; help: string }> = {
  // the brief's own words (lane I): an evidenced cause and a hypothesis stay distinguishable on screen
  SUPPORTED_CAUSE: {
    label: "Supported cause (evidenced)",
    tone: "ok",
    help: "A logged change starts when the change starts, and its check against the unaffected groups backs it up.",
  },
  HYPOTHESIS: { label: "Hypothesis", tone: "watch", help: "Argus found where it happens, but no logged change is proven to cause it yet." },
  EXPECTED: { label: "Planned change", tone: "ok", help: "A plan or calendar entry explains the move and delivery followed it, so nobody was woken." },
  DATA_ISSUE: { label: "Late data", tone: "watch", help: "The data had not fully arrived; Argus waited instead of raising a false alarm." },
  UNEXPLAINED: { label: "Checking", tone: "probe", help: "No explanation yet: the investigation is still running or found nothing it could prove." },
};

export const STATE: Record<IncidentState, { label: string; tone: Tone; help: string }> = {
  open: { label: "New", tone: "alarm", help: "Just detected." },
  investigating: { label: "Investigating", tone: "probe", help: "Argus is working through its checks." },
  explained: { label: "Explained", tone: "watch", help: "The cause is known; the metric has not recovered yet." },
  monitoring: { label: "Recovering", tone: "watch", help: "Back in its usual range; Argus waits for three normal hours before it closes the incident." },
  resolved: { label: "Resolved", tone: "ok", help: "Three normal hours in a row: closed by Argus." },
};

/** Names for the dimensions a segment is cut by. */
const DIMENSION: Record<string, string> = {
  country: "Country",
  platform: "Platform",
  provider: "Payment provider",
  channel: "Channel",
  category: "Category",
  advertiser_id: "Advertiser",
};

const COUNTRY: Record<string, string> = { DE: "Germany", FR: "France", UK: "United Kingdom", ES: "Spain", NL: "Netherlands", IT: "Italy", AT: "Austria" };
const PLATFORM: Record<string, string> = { android: "Android", ios: "iOS", web: "Web" };

export function dimensionName(dim: string): string {
  return DIMENSION[dim] ?? dim.replace(/_/g, " ");
}

export function valueName(dim: string, value: string): string {
  if (dim === "country") return COUNTRY[value] ?? value;
  if (dim === "platform") return PLATFORM[value] ?? value;
  return value;
}

export interface WhereCell {
  dim: string;
  /** "Country" */
  name: string;
  /** "Germany" */
  value: string;
}

const ORDER = ["country", "platform", "provider", "channel", "category", "advertiser_id"];

/** The segment (or scope) as "where" cells, in the fixed dimension order of the reports; lists read "Germany and France". */
export function whereCells(segment: Where): WhereCell[] {
  const entries = Object.entries(segment).sort(([a], [b]) => ORDER.indexOf(a) - ORDER.indexOf(b));
  return entries.map(([dim, value]) => {
    const names = (Array.isArray(value) ? value : [value]).map((v) => valueName(dim, v));
    const joined = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : (names[0] ?? "");
    return { dim, name: dimensionName(dim), value: joined };
  });
}

/** "Android in Germany via PayCo", or "the whole shop" for the empty segment. */
export function wherePhrase(segment: Where): string {
  const cells = whereCells(segment);
  if (!cells.length) return "the whole shop";
  const by = Object.fromEntries(cells.map((c) => [c.dim, c.value]));
  const parts: string[] = [];
  if (by.platform) parts.push(by.platform);
  if (by.country) parts.push(`${parts.length ? "in " : ""}${by.country}`);
  if (by.provider) parts.push(`via ${by.provider}`);
  for (const c of cells) if (!["platform", "country", "provider"].includes(c.dim)) parts.push(`${c.name.toLowerCase()} ${c.value}`);
  return parts.join(" ");
}

/** "Payment success fell 33.6% for Android in Germany via PayCo" */
export function storyHeadline(graph: Graph | null, node: string, changePct: number | null, segment: Where): string {
  const name = metricName(graph, node);
  const where = wherePhrase(segment);
  if (changePct === null || !Number.isFinite(changePct)) return `${name} moved for ${where}`;
  const verb = changePct < 0 ? "fell" : "rose";
  return `${name} ${verb} ${Math.abs(changePct).toFixed(1)}% for ${where}`;
}

/**
 * Server-written lines (the digest) in the overview's words: "840 series-hours" becomes "840 metric checks",
 * "payment_success_rate |z| 9.4" becomes "Payment success far off its usual level", verdict codes become their
 * plain names. Numbers are kept as they are.
 */
export function plainWords(text: string, graph: Graph | null = null): string {
  return monitoringText(text)
    .replace(/\|z\| between ([\d.]+) and ([\d.]+), below the alarm line/g, "moves noticed but below the alarm threshold")
    .replace(/\b([a-z][a-z_]*[a-z]) \|z\| [\d.]+/g, (_, id: string) => `${metricName(graph, id)} far off its usual level`)
    .replace(/(\d[\d,]*) series-hours?/g, "$1 metric checks")
    .replace(/\bwiggles\b/g, "small moves")
    .replace(/\bwiggle\b/g, "small move")
    .replace(/\bedge tests\b/g, "formula checks")
    .replace(/\bedge test\b/g, "formula check")
    .replace(/\bLLM calls?\b/g, "AI calls")
    .replace(/\b(SUPPORTED_CAUSE|HYPOTHESIS|EXPECTED|DATA_ISSUE|UNEXPLAINED)\b/g, (code: string) => VERDICT[code as Verdict].label);
}

/** How far a metric is off its usual level, in words; the lines are the watcher's own thresholds. */
export function unusualness(z: number | null, wiggle: number, alarm: number): { word: string; tone: Tone } {
  if (z === null) return { word: "not checked this hour", tone: "muted" };
  if (z >= alarm) return { word: "alarm", tone: "alarm" };
  if (z >= wiggle) return { word: "unusual", tone: "watch" };
  return { word: "normal", tone: "ok" };
}

export interface GlossaryEntry {
  /** the term as the internal pages and the reports write it */
  term: string;
  /** the plain name the first level uses */
  plain: string;
  /** one or two sentences, no jargon */
  meaning: string;
}

/** Every internal term the first level avoids, with the words it uses instead. */
export const GLOSSARY: GlossaryEntry[] = [
  {
    term: "|z|",
    plain: "How unusual",
    meaning:
      "How far this hour is from the same hour in the last four weeks, counted in typical swings. Under 2 is ordinary, from 2 a little off, 5 or more raises an alarm.",
  },
  { term: "Wiggle", plain: "Small move", meaning: "A move between 2 and 5 on the unusualness scale: noted, never paged." },
  { term: "Alarm line", plain: "Alarm threshold", meaning: "5 on the unusualness scale, or 3.5 in two of the last three hours. Only then does Argus open an investigation." },
  { term: "Series-hours", plain: "Metric checks", meaning: "One metric checked for one hour. Seven key metrics for 120 hours are 840 checks." },
  {
    term: "Edge test",
    plain: "Formula check",
    meaning: "Every link in the metric map (orders = visits x conversion, ...) is re-tested against the data once a day; a link that stops holding is flagged before it is trusted.",
  },
  {
    term: "LMDI",
    plain: "Exact split",
    meaning: "A standard way to split a change into the factors of its formula so the shares add up to exactly 100%, with nothing left over.",
  },
  { term: "Segment search", plain: "Where it is", meaning: "Cutting the drop by country, platform and payment provider until it sits in the smallest group that still carries it." },
  {
    term: "Holdout",
    plain: "Comparison group",
    meaning: "The part of a suspect's reach that did not break. If the suspect were the cause, that part would have dropped too.",
  },
  { term: "Placebo test", plain: "Normal-week check", meaning: "The same test on earlier normal weeks; a real cause does not show up there." },
  {
    term: "Receipt",
    plain: "Evidence",
    meaning: "The SQL query behind a number, pinned to the moment it ran and hashed, so anyone can re-run it and get the same result.",
  },
  { term: "SUPPORTED_CAUSE", plain: VERDICT.SUPPORTED_CAUSE.label, meaning: VERDICT.SUPPORTED_CAUSE.help },
  { term: "HYPOTHESIS", plain: VERDICT.HYPOTHESIS.label, meaning: VERDICT.HYPOTHESIS.help },
  { term: "EXPECTED", plain: VERDICT.EXPECTED.label, meaning: VERDICT.EXPECTED.help },
  { term: "DATA_ISSUE", plain: VERDICT.DATA_ISSUE.label, meaning: VERDICT.DATA_ISSUE.help },
  { term: "PROBATION", plain: "On trial", meaning: "A new link in the metric map that is used but not yet trusted, until the data supports it." },
  {
    term: "Symptom",
    plain: "Knock-on effect",
    meaning: "A metric that moved only because the root metric moved (orders fall when payments fail); Argus files one incident, not one per symptom.",
  },
  {
    term: "pass@1",
    plain: "Runs right",
    meaning: "The share of sealed test runs Argus got right on its first and only try: the right page with the right cause, or rightly no page at all.",
  },
  {
    term: "Health score",
    plain: "Shop health",
    meaning: "The average of four checks, each a share of things that passed: data delivered, key metrics in their usual range, formula checks holding, incidents closed. No weights, no model.",
  },
];

/** The glossary entry for a term or its plain name (case-insensitive), for tooltips. */
export function gloss(term: string): GlossaryEntry | undefined {
  const key = term.toLowerCase();
  return GLOSSARY.find((g) => g.term.toLowerCase() === key || g.plain.toLowerCase() === key);
}

/** A glossary tooltip: the plain meaning of an internal term ("LMDI: A standard way ..."). */
export function tip(term: string): string | undefined {
  const g = gloss(term);
  return g ? `${g.term === g.plain ? g.plain : `${g.plain} (${g.term})`}: ${g.meaning}` : undefined;
}
