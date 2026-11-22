import { quantity } from "../../lib/format";
import type { RunView } from "../../lib/store";
import type { GraphNode, Incident, Segment, TrailStep } from "../../lib/types";

const DAY = 86_400_000;
export const HISTORY_PERIODS = [
  ["all", "All time"],
  ["1y", "One year"],
  ["30d", "Last 30 days"],
] as const;
export type AnalyticsPeriod = "24h" | "7d" | (typeof HISTORY_PERIODS)[number][0];

export interface AnalyticsQuery {
  metric: string;
  segment: Segment;
  period: AnalyticsPeriod;
}

export interface AnalyticsWindow {
  start: number | null;
  end: number | null;
}

const days: Record<Exclude<AnalyticsPeriod, "all">, number> = { "24h": 1, "7d": 7, "30d": 30, "1y": 365 };

export function time(ts: unknown): number | null {
  if (typeof ts !== "string" || !ts) return null;
  const parsed = Date.parse(/(?:Z|[+-]\d\d:\d\d)$/i.test(ts) ? ts : `${ts}Z`);
  return Number.isFinite(parsed) ? parsed : null;
}

export function analyticsWindow(asOf: string | null, period: AnalyticsPeriod): AnalyticsWindow {
  const end = time(asOf);
  return { start: end === null || period === "all" ? null : end - days[period] * DAY, end };
}

function inWindow(at: number | null, window: AnalyticsWindow): at is number {
  return at !== null && window.end !== null && at <= window.end && (window.start === null || at >= window.start);
}

const utc = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium", timeStyle: "short", timeZone: "UTC",
});
export const dateTime = (at: number) => `${utc.format(at)} UTC`;
const hasScope = (segment: Segment, filter: Segment) =>
  Object.entries(filter).every(([dim, value]) => Object.hasOwn(segment, dim) && segment[dim] === value);
const exactScope = (a: Segment, b: Segment) => Object.keys(a).length === Object.keys(b).length && hasScope(a, b);

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asSegment(value: unknown): Segment | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const entries = Object.entries(value);
  return entries.every(([, part]) => typeof part === "string" && part.length > 0) ? Object.fromEntries(entries) : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function metricValue(value: number, unit: string): string {
  switch (unit) {
    case "ratio":
      return `${quantity({ value, unit, receipt: null })}×`;
    case "eur_per_unit":
      return quantity({ value, unit: "eur", receipt: null });
    default:
      return quantity({ value, unit, receipt: null });
  }
}

export function visibleIncident(view: RunView, incident: Incident, window: AnalyticsWindow): boolean {
  const summary = view.incidents[incident.id];
  const updated = time(incident.updated_at);
  const known = time(incident.findings.as_of);
  return Boolean(summary && updated !== null && updated === time(summary.updatedAt) && summary.state === incident.state
    && window.end !== null && updated <= window.end && known !== null && known <= window.end);
}

export function selectIncident(view: RunView, incidents: readonly Incident[], query: AnalyticsQuery, window: AnalyticsWindow, id?: string) {
  if (window.end === null) return undefined;
  const asOf = window.end;
  return incidents.filter((incident) => {
    if (id && incident.id !== id) return false;
    if (!visibleIncident(view, incident, window)) return false;
    const { findings } = incident;
    if (query.metric !== findings.observed.node && query.metric !== findings.root?.node) return false;
    if (!hasScope(incident.segment, query.segment) && !hasScope(findings.observed.segment, query.segment)) return false;
    const start = time(incident.opened_at);
    const resolved = time(incident.resolved_at);
    return start !== null && start <= asOf && (resolved === null || window.start === null || resolved >= window.start);
  }).sort((a, b) => view.incidents[b.id].lastSeq - view.incidents[a.id].lastSeq || a.id.localeCompare(b.id))[0];
}

export interface HistoryPoint {
  at: number;
  observed: number | null;
  expected: number | null;
  band: readonly [number, number] | null;
  receipts: readonly string[];
}

export function historyPoints(view: RunView, query: AnalyticsQuery, window: AnalyticsWindow, incident?: Incident): HistoryPoint[] {
  if (window.end === null) return [];
  const asOf = window.end;
  const points = new Map<number, HistoryPoint>();
  const findings = incident?.findings;
  // Older findings may carry raw samples. Read them only when the step identifies their metric and exact scope.
  for (const step of findings?.trail ?? []) {
    const { node, segment, series } = step.data ?? {};
    const scope = asSegment(segment);
    if (step.tool !== "get_series" || node !== query.metric || !scope || !exactScope(scope, query.segment) || !Array.isArray(series)) continue;
    for (const raw of series) {
      const row = asObject(raw);
      const at = time(row.hour);
      const observed = finite(row.value);
      const expected = finite(row.expected);
      if (inWindow(at, window) && (observed !== null || expected !== null)) {
        points.set(at, { at, observed, expected, band: null, receipts: step.receipts });
      }
    }
  }

  const observation = findings?.observed;
  const observationAt = time(findings?.window.start);
  if (observation?.node === query.metric && exactScope(observation.segment, query.segment)
    && observationAt === time(findings?.window.end) && inWindow(observationAt, window) && !points.has(observationAt)) {
    points.set(observationAt, {
      at: observationAt,
      observed: finite(observation.observed.value),
      expected: finite(observation.expected.value),
      band: null,
      receipts: [...new Set([observation.observed.receipt, observation.expected.receipt].filter((id): id is string => Boolean(id)))],
    });
  }

  for (const anomaly of view.anomalies) {
    const at = time(anomaly.hour);
    const detected = time(anomaly.detected_at);
    if (anomaly.node !== query.metric || !exactScope(anomaly.segment, query.segment)
      || !inWindow(at, window) || detected === null || detected > asOf) continue;
    const point = points.get(at);
    points.set(at, {
      at,
      observed: finite(anomaly.observed),
      expected: finite(anomaly.expected),
      band: anomaly.band.every(Number.isFinite) ? anomaly.band : null,
      receipts: [...new Set([...anomaly.receipts, ...(point?.receipts ?? [])])],
    });
  }
  return [...points.values()].sort((a, b) => a.at - b.at);
}

export interface HistoryMarker {
  id: string;
  at: number;
  kind: "incident" | "release";
  label: string;
  detail: string;
  receipts: readonly string[];
}

export function historyMarkers(incident: Incident | undefined, window: AnalyticsWindow): HistoryMarker[] {
  if (!incident) return [];
  const markers: HistoryMarker[] = [];
  const opened = time(incident.opened_at);
  if (inWindow(opened, window)) {
    markers.push({ id: incident.id, at: opened, kind: "incident", label: `Incident ${incident.id}`, detail: incident.title, receipts: [] });
  }

  const addRelease = (raw: unknown, receipts: readonly string[], verdict?: string) => {
    const event = asObject(raw);
    const at = time(event.ts);
    if ((event.kind !== "release" && event.kind !== "deploy") || typeof event.ref !== "string" || !inWindow(at, window)) return;
    if (markers.some((marker) => marker.id === event.ref)) return;
    markers.push({
      id: event.ref, at, kind: "release", label: verdict ?? "Release checked",
      detail: typeof event.description === "string" ? event.description : event.ref,
      receipts,
    });
  };
  const visibleReceipts = new Set(incident.findings.trail.flatMap((step) => step.receipts));
  for (const check of incident.findings.ruled_out) {
    const evidence = check.receipts.filter((receipt) => visibleReceipts.has(receipt));
    if (evidence.length) addRelease(check.evidence, evidence, check.result === "refuted" ? "Release ruled out" : "Release check inconclusive");
  }
  const root = incident.findings.root?.evidence;
  const isRootRelease = (raw: unknown) => root && asObject(raw).ref === root.ref;
  for (const step of incident.findings.trail) {
    const events = step.data?.events;
    if (step.tool !== "list_events" || !Array.isArray(events)) continue;
    for (const raw of events) {
      const verdict = isRootRelease(raw) && incident.verdict === "SUPPORTED_CAUSE" ? "Release supported by evidence" : undefined;
      addRelease(raw, step.receipts, verdict);
    }
  }
  return markers.sort((a, b) => a.at - b.at || a.id.localeCompare(b.id));
}

export interface DistributionRow {
  segment: Segment;
  parent: Segment;
  change: number;
  volumeShare: number;
  explainedShare: number;
  receipts: readonly string[];
}

type MeasurementWindow = Incident["findings"]["window"];

/** Segment search runs over the trigger window, before the investigation can move its start back. */
export function measurementWindow(view: RunView, incident: Incident | undefined): MeasurementWindow | undefined {
  const findings = incident?.findings;
  if (!findings) return undefined;
  const trigger = view.anomalies.find(({ id }) => id === findings.anomaly_id);
  return trigger ? { start: trigger.onset, end: trigger.hour } : findings.window;
}

function windowIncludes(window: AnalyticsWindow, measurement: MeasurementWindow | undefined): boolean {
  return inWindow(time(measurement?.start), window) && inWindow(time(measurement?.end), window);
}

export function scopedIncidentChange(
  incident: Incident | undefined, query: AnalyticsQuery, window: AnalyticsWindow, measurement: MeasurementWindow | undefined,
) {
  const findings = incident?.findings;
  const root = findings?.root;
  if (!findings || !root || root.node !== query.metric || !exactScope(root.segment, query.segment)
    || !windowIncludes(window, measurement)) return null;
  const receipt = root.change_pct.receipt;
  return receipt && findings.trail.some((step) => step.receipts.includes(receipt)) ? root.change_pct : null;
}

function pathRows(step: TrailStep, metric: GraphNode): DistributionRow[] {
  const { start, path } = step.data ?? {};
  let parent = start === undefined ? {} : asSegment(start);
  if (!parent || !Array.isArray(path)) return [];
  let remaining = metric.dims.filter((dim) => !Object.hasOwn(parent!, dim));
  let offset = 1;
  const rows: DistributionRow[] = [];
  for (const raw of path) {
    const cell = asObject(raw);
    const segment = asSegment(cell.segment);
    const change = finite(cell.rel_change);
    const volumeShare = finite(cell.volume_share);
    const explainedShare = finite(cell.ep);
    if (!segment || !hasScope(segment, parent) || Object.keys(segment).length !== Object.keys(parent).length + 1
      || change === null || volumeShare === null || explainedShare === null) return [];
    const dim = Object.keys(segment).find((key) => !Object.hasOwn(parent!, key));
    const index = remaining.findIndex((key) => key === dim);
    if (index < 0) return [];
    const receipt = step.receipts[offset + index];
    rows.push({ segment, parent, change, volumeShare, explainedShare, receipts: receipt ? [receipt] : [] });
    offset += remaining.length;
    remaining = remaining.filter((key) => key !== dim);
    parent = segment;
  }
  // segment_search records the starting total, then one receipt per remaining dimension at each descent.
  // One final unsuccessful descent can add a complete set of receipts.
  const mapped = step.receipts.length === offset || step.receipts.length === offset + remaining.length;
  return mapped ? rows : rows.map((row) => ({ ...row, receipts: step.receipts }));
}

export function distributionRows(
  incident: Incident | undefined, metric: GraphNode, window: AnalyticsWindow, filter: Segment, measurement: MeasurementWindow | undefined,
): DistributionRow[] {
  const findings = incident?.findings;
  if (!findings || !windowIncludes(window, measurement)) return [];
  const node = findings.root?.node ?? findings.observed.node;
  if (node !== metric.id) return [];
  const step = findings.trail.find((candidate) => candidate.tool === "segment_search" && Array.isArray(candidate.data?.path));
  return step ? pathRows(step, metric).filter((row) => hasScope(row.segment, filter)) : [];
}
