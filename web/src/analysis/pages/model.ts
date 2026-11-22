import { segmentLabel } from "../../lib/format";
import type { IncidentView, RunView } from "../../lib/store";
import type { Graph, Incident, Segment } from "../../lib/types";
import { ANALYSIS_PERIODS, segmentKey, type AnalysisPeriod, type AnalysisQuery } from "../shell/query";

export const AD_METRICS = ["ad_impressions", "ad_clicks", "ad_spend", "ad_conversions", "attributed_gmv", "ctr", "cpc", "cpa", "roas", "planned_spend", "pacing_ratio"];
export const FUNNEL_METRICS = ["sessions", "product_views", "carts", "checkouts", "payment_attempts", "payment_successes", "orders"];

export interface AnalysisWindow { start: number | null; end: number | null }

function time(ts: string | null): number | null {
  if (!ts) return null;
  // The API also serves naive timestamps, expressed in UTC by the replay clock.
  const value = Date.parse(/(?:Z|[+-]\d\d:\d\d)$/i.test(ts) ? ts : `${ts}Z`);
  return Number.isFinite(value) ? value : null;
}

export function analysisWindow(asOf: string | null, period: AnalysisPeriod): AnalysisWindow {
  const end = time(asOf);
  const hours = ANALYSIS_PERIODS.find(([id]) => id === period)?.[2];
  return { start: end !== null && hours ? end - hours * 3_600_000 : null, end };
}

export function inWindow(ts: string, window: AnalysisWindow): boolean {
  const point = time(ts);
  return point !== null && window.end !== null && point <= window.end && (window.start === null || point >= window.start);
}

export function matchesSegment(candidate: Segment, filter: Segment): boolean {
  return Object.entries(filter).every(([dimension, value]) => Object.hasOwn(candidate, dimension) && candidate[dimension] === value);
}

export function matchesIncident(incident: IncidentView, query: AnalysisQuery, window: AnalysisWindow): boolean {
  const opened = time(incident.openedAt);
  const updated = time(incident.updatedAt);
  return (incident.state === "resolved" ? inWindow(incident.updatedAt, window) : opened !== null && window.end !== null && opened <= window.end)
    && updated !== null && window.end !== null && updated <= window.end
    && (!query.metric || incident.root_node === query.metric)
    && matchesSegment(incident.segment, query.segment);
}

export function analysisIncidents(view: RunView, query: AnalysisQuery, window: AnalysisWindow) {
  return Object.values(view.incidents)
    .filter((incident) => matchesIncident(incident, query, window))
    .sort((a, b) => Number(a.state === "resolved") - Number(b.state === "resolved") || b.lastSeq - a.lastSeq);
}

export function analysisSignals(view: RunView, query: AnalysisQuery, window: AnalysisWindow) {
  return view.anomalies.filter((a) =>
    inWindow(a.hour, window) && (!query.metric || a.node === query.metric) && matchesSegment(a.segment, query.segment),
  ).slice().reverse();
}

export function visibleFindings(incident: Incident, summaries: IncidentView[], window: AnalysisWindow): boolean {
  const summary = summaries.find((item) => item.id === incident.id);
  if (!summary || summary.state !== incident.state || summary.updatedAt !== incident.updated_at) return false;
  const known = time(incident.findings.as_of);
  return known !== null && window.end !== null && known <= window.end;
}

export function observedSegments(view: RunView, graph: Graph | null, metric: string) {
  const allowed = new Map(graph?.nodes.map((node) => [node.id, new Set(node.dims)]));
  const sources = [
    ...view.anomalies.map((signal) => ({ metric: signal.node, segment: signal.segment })),
    ...Object.values(view.incidents).map((incident) => ({ metric: incident.root_node, segment: incident.segment })),
  ];
  const found = new Map<string, Segment>();
  function add(segment: Segment) {
    if (Object.keys(segment).length) found.set(segmentKey(segment), segment);
  }
  for (const source of sources) {
    if (metric && metric !== source.metric) continue;
    const dims = allowed.get(source.metric);
    if (!dims) continue;
    const segment = Object.fromEntries(Object.entries(source.segment).filter(([dim]) => dims.has(dim)));
    add(segment);
    for (const [dim, value] of Object.entries(segment)) add({ [dim]: value });
  }
  return [...found.values()].sort((a, b) => segmentLabel(a).localeCompare(segmentLabel(b)));
}
