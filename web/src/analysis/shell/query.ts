import type { Segment } from "../../lib/types";

export const ANALYSIS_PAGES = [
  ["overview", "Overview"],
  ["metrics", "Metrics"],
  ["segments", "Segments"],
  ["countries", "Countries"],
  ["ads", "Ads"],
  ["funnel", "Funnel"],
  ["incidents", "Incidents"],
  ["live-fix", "Live Fix"],
  ["changes", "Changes"],
] as const;

export const ANALYSIS_PERIODS = [
  ["24h", "Last 24 hours", 24],
  ["7d", "Last 7 days", 168],
  ["30d", "Last 30 days", 720],
  ["1y", "Last year", 8760],
  ["all", "All retained", null],
] as const;

export type AnalysisPage = (typeof ANALYSIS_PAGES)[number][0];
export type AnalysisPeriod = (typeof ANALYSIS_PERIODS)[number][0];
export interface AnalysisQuery {
  page: AnalysisPage;
  metric: string;
  segment: Segment;
  period: AnalysisPeriod;
  incidentId?: string;
  runId?: string;
}

export const DEFAULT_QUERY: AnalysisQuery = { page: "overview", metric: "", segment: {}, period: "7d" };

export function segmentKey(segment: Segment): string {
  return JSON.stringify(Object.entries(segment).sort(([a], [b]) => a.localeCompare(b)));
}

function readSegment(raw: string | null): Segment {
  if (!raw || raw.length > 2048) return {};
  try {
    const entries: unknown = JSON.parse(raw);
    if (!Array.isArray(entries) || !entries.every((entry) =>
      Array.isArray(entry) && entry.length === 2 && entry.every((part) => typeof part === "string" && part.length > 0),
    )) return {};
    return Object.fromEntries(entries);
  } catch {
    return {};
  }
}

export function readAnalysisQuery(search: string): AnalysisQuery | null {
  const params = new URLSearchParams(search);
  const page = ANALYSIS_PAGES.find(([id]) => id === params.get("analysis"))?.[0];
  if (!page) return null;
  return {
    page,
    metric: params.get("metric") ?? "",
    segment: readSegment(params.get("segment")),
    period: ANALYSIS_PERIODS.find(([id]) => id === params.get("period"))?.[0] ?? DEFAULT_QUERY.period,
    ...(page === "live-fix" && {
      incidentId: params.get("fixIncident") || undefined,
      runId: params.get("run") || undefined,
    }),
  };
}

export function analysisURL(current: string, query: AnalysisQuery | null): URL {
  const url = new URL(current);
  if (url.searchParams.get("view") === "settings") url.searchParams.delete("tab");
  for (const key of ["view", "incident", "receipt", "analysis", "metric", "segment", "period", "fixIncident", "run"]) url.searchParams.delete(key);
  if (query) {
    url.searchParams.set("view", "dashboard");
    url.searchParams.set("analysis", query.page);
    if (query.metric) url.searchParams.set("metric", query.metric);
    if (Object.keys(query.segment).length) url.searchParams.set("segment", segmentKey(query.segment));
    if (query.period !== DEFAULT_QUERY.period) url.searchParams.set("period", query.period);
    if (query.page === "live-fix") {
      if (query.incidentId) url.searchParams.set("fixIncident", query.incidentId);
      if (query.runId) url.searchParams.set("run", query.runId);
    }
  }
  return url;
}
