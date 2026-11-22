// Derived analysis views over the active stream and the incident findings: the hourly detection trend, a
// comparison of the latest scored hours with the hours before, the per-metric deviation history, segment and
// incident-cohort breakdowns, driver decomposition and the funnel. Every value comes from scored ticks, anomaly
// events, incident updates, graph edge tests or recorded findings; nothing is interpolated or estimated here.

import type { HourStat, IncidentView, RunView } from "../../lib/store";
import type { Anomaly, Graph, Incident, Segment, Thresholds } from "../../lib/types";
import { time } from "../analytics/model";
import { inWindow, matchesSegment, type AnalysisWindow } from "../pages/model";

const HOUR = 3_600_000;

export type Level = "calm" | "watch" | "alarm";

export function level(z: number, thresholds: Thresholds): Level {
  return z >= thresholds.alarm_z ? "alarm" : z >= thresholds.wiggle_z ? "watch" : "calm";
}

function peakOf(hour: HourStat, metric: string): number | null {
  if (metric) {
    const z = hour.byNode?.[metric];
    return typeof z === "number" && Number.isFinite(z) ? z : null;
  }
  return hour.z.length ? Math.max(...hour.z) : null;
}

export interface TrendPoint {
  at: number;
  /** the highest |z| scored this hour (for one metric, or across every scored metric) */
  peak: number | null;
  /** scored series at or above the wiggle threshold but below the alarm threshold */
  watch: number;
  /** scored series at or above the alarm threshold */
  alarm: number;
  /** incidents open at this tick */
  open: number;
  /** the lowest source completeness for the hour (1 = every table delivered) */
  completeness: number;
}

/** One point per scored hour inside the window, oldest first. */
export function hourlyTrend(hours: readonly HourStat[], thresholds: Thresholds, window: AnalysisWindow, metric = ""): TrendPoint[] {
  return hours.flatMap((hour) => {
    const at = time(hour.hour);
    if (at === null || !inWindow(hour.hour, window)) return [];
    const values = metric ? [peakOf(hour, metric)].filter((z): z is number => z !== null) : hour.z;
    return [{
      at,
      peak: values.length ? Math.max(...values) : null,
      watch: values.filter((z) => level(z, thresholds) === "watch").length,
      alarm: values.filter((z) => level(z, thresholds) === "alarm").length,
      open: hour.open,
      completeness: hour.completeness,
    }];
  });
}

export interface PeriodStats {
  /** exclusive start and inclusive end of the period, in ms */
  from: number;
  to: number;
  /** scored hours the stream holds for this period */
  hours: number;
  meanPeak: number | null;
  peak: number | null;
  /** scored hours whose peak reached the wiggle threshold */
  watchHours: number;
  /** scored hours whose peak reached the alarm threshold */
  alarmHours: number;
  anomalies: number;
  incidentsOpened: number;
  minCompleteness: number | null;
}

export interface PeriodComparison {
  span: number;
  current: PeriodStats;
  /** null when the stream holds no scored hour before the current period */
  previous: PeriodStats | null;
}

function periodStats(view: RunView, metric: string, segment: Segment, from: number, to: number): PeriodStats {
  const inside = (ts: string) => {
    const at = time(ts);
    return at !== null && at > from && at <= to;
  };
  const peaks: number[] = [];
  const completeness: number[] = [];
  for (const hour of view.hours) {
    if (!inside(hour.hour)) continue;
    const peak = peakOf(hour, metric);
    if (peak === null) continue;
    peaks.push(peak);
    completeness.push(hour.completeness);
  }
  const { wiggle_z: wiggle, alarm_z: alarm } = view.thresholds;
  return {
    from,
    to,
    hours: peaks.length,
    meanPeak: peaks.length ? peaks.reduce((sum, z) => sum + z, 0) / peaks.length : null,
    peak: peaks.length ? Math.max(...peaks) : null,
    watchHours: peaks.filter((z) => z >= wiggle).length,
    alarmHours: peaks.filter((z) => z >= alarm).length,
    anomalies: view.anomalies.filter((a) => inside(a.hour) && (!metric || a.node === metric) && matchesSegment(a.segment, segment)).length,
    incidentsOpened: Object.values(view.incidents).filter((incident) =>
      inside(incident.openedAt) && (!metric || incident.root_node === metric) && matchesSegment(incident.segment, segment)).length,
    minCompleteness: completeness.length ? Math.min(...completeness) : null,
  };
}

/** The latest `span` scored hours against the `span` hours before them, both read from the active stream. */
export function compareRecent(view: RunView, metric: string, segment: Segment, span = 24): PeriodComparison | null {
  const last = view.hours.length ? time(view.hours[view.hours.length - 1].hour) : null;
  if (last === null) return null;
  const current = periodStats(view, metric, segment, last - span * HOUR, last);
  const previous = periodStats(view, metric, segment, last - 2 * span * HOUR, last - span * HOUR);
  return { span, current, previous: previous.hours ? previous : null };
}

export interface HeatCell {
  at: number;
  z: number | null;
  /** an anomaly on this metric (any scope) was scored for this hour */
  flagged: boolean;
}

export interface HeatRow {
  metric: string;
  cells: HeatCell[];
  peak: number | null;
  anomalies: number;
}

/** The |z| of each scored metric per hour, with the hours that opened an anomaly marked. */
export function deviationHistory(
  view: RunView, window: AnalysisWindow, order: readonly string[] = [], only?: readonly string[],
): { columns: number[]; rows: HeatRow[] } {
  const hours = view.hours.filter((hour) => inWindow(hour.hour, window) && time(hour.hour) !== null);
  const columns = hours.map((hour) => time(hour.hour) as number);
  const seen = new Set(hours.flatMap((hour) => Object.keys(hour.byNode ?? {})).filter((id) => !only || only.includes(id)));
  const metrics = [...order.filter((id) => seen.has(id)), ...[...seen].filter((id) => !order.includes(id)).sort()];
  const flagged = new Set(view.anomalies.flatMap((a) => {
    const at = time(a.hour);
    return at === null ? [] : [`${a.node}@${at}`];
  }));
  const rows = metrics.map((metric) => {
    const cells = hours.map((hour, index) => {
      const z = hour.byNode?.[metric];
      return { at: columns[index], z: typeof z === "number" && Number.isFinite(z) ? z : null, flagged: flagged.has(`${metric}@${columns[index]}`) };
    });
    const scored = cells.flatMap((cell) => (cell.z === null ? [] : [cell.z]));
    return {
      metric,
      cells,
      peak: scored.length ? Math.max(...scored) : null,
      anomalies: view.anomalies.filter((a) => a.node === metric && inWindow(a.hour, window)).length,
    };
  });
  return { columns, rows };
}

export interface SegmentRow {
  dimension: string;
  value: string;
  anomalies: number;
  falls: number;
  rises: number;
  incidents: number;
  /** summed absolute incident severity, EUR */
  impact: number;
  peakZ: number | null;
}

/** Every dimension value that appears in the matching anomalies or incidents, with what was seen there. */
export function segmentBreakdown(signals: readonly Anomaly[], incidents: readonly IncidentView[]): { rows: SegmentRow[]; wholeShop: number } {
  const rows = new Map<string, SegmentRow>();
  const row = (dimension: string, value: string) => {
    const key = JSON.stringify([dimension, value]);
    let found = rows.get(key);
    if (!found) {
      found = { dimension, value, anomalies: 0, falls: 0, rises: 0, incidents: 0, impact: 0, peakZ: null };
      rows.set(key, found);
    }
    return found;
  };
  let wholeShop = 0;
  for (const signal of signals) {
    const entries = Object.entries(signal.segment);
    if (!entries.length) wholeShop += 1;
    for (const [dimension, value] of entries) {
      const target = row(dimension, value);
      target.anomalies += 1;
      if (signal.direction === "down") target.falls += 1;
      else target.rises += 1;
      const z = Math.abs(signal.z);
      if (Number.isFinite(z)) target.peakZ = Math.max(target.peakZ ?? 0, z);
    }
  }
  for (const incident of incidents) {
    for (const [dimension, value] of Object.entries(incident.segment)) {
      const target = row(dimension, value);
      target.incidents += 1;
      if (Number.isFinite(incident.severity_eur)) target.impact += Math.abs(incident.severity_eur);
    }
  }
  return {
    rows: [...rows.values()].sort((a, b) => a.dimension.localeCompare(b.dimension)
      || b.impact - a.impact || b.anomalies - a.anomalies || a.value.localeCompare(b.value)),
    wholeShop,
  };
}

export interface CohortRow {
  /** UTC day the incidents were opened, YYYY-MM-DD */
  day: string;
  opened: number;
  active: number;
  explained: number;
  resolved: number;
  /** summed absolute severity, EUR */
  impact: number;
  /** mean hours from opening to resolution, over the resolved incidents of the cohort */
  hoursToResolve: number | null;
}

/** Incidents grouped by the UTC day they opened, with where each cohort stands now. */
export function incidentCohorts(incidents: readonly IncidentView[]): CohortRow[] {
  const cohorts = new Map<string, CohortRow & { resolveHours: number[] }>();
  for (const incident of incidents) {
    const opened = time(incident.openedAt);
    if (opened === null) continue;
    const day = new Date(opened).toISOString().slice(0, 10);
    let cohort = cohorts.get(day);
    if (!cohort) {
      cohort = { day, opened: 0, active: 0, explained: 0, resolved: 0, impact: 0, hoursToResolve: null, resolveHours: [] };
      cohorts.set(day, cohort);
    }
    cohort.opened += 1;
    if (Number.isFinite(incident.severity_eur)) cohort.impact += Math.abs(incident.severity_eur);
    if (incident.state === "resolved") {
      cohort.resolved += 1;
      const closed = time(incident.updatedAt);
      if (closed !== null && closed >= opened) cohort.resolveHours.push((closed - opened) / HOUR);
    } else if (incident.state === "explained" || incident.state === "monitoring") cohort.explained += 1;
    else cohort.active += 1;
  }
  return [...cohorts.values()].sort((a, b) => b.day.localeCompare(a.day)).map(({ resolveHours, ...cohort }) => ({
    ...cohort,
    hoursToResolve: resolveHours.length ? resolveHours.reduce((sum, h) => sum + h, 0) / resolveHours.length : null,
  }));
}

export interface DriverRow {
  node: string;
  /** share of the decomposed change this input explains (can be negative when it moved the other way) */
  share: number;
  /** the input's contribution in the decomposed metric's unit */
  value: number;
  receipt: string | null;
}

export interface DriverDecomposition {
  incidentId: string;
  node: string;
  segment: Segment;
  window: { start: string; end: string };
  rows: DriverRow[];
  explainedShare: number;
  unexplainedShare: number;
}

/** The latest recorded decomposition among the visible incidents, optionally for one metric. */
export function driverDecomposition(incidents: readonly Incident[], metric = ""): DriverDecomposition | null {
  const matching = incidents.filter(({ findings }) => findings.decomposed_node && findings.decomposition.length
    && (!metric || [findings.decomposed_node, findings.observed.node, findings.root?.node].includes(metric)));
  const latest = matching.sort((a, b) => (time(b.updated_at) ?? 0) - (time(a.updated_at) ?? 0) || a.id.localeCompare(b.id))[0];
  if (!latest) return null;
  const { findings } = latest;
  return {
    incidentId: latest.id,
    node: findings.decomposed_node as string,
    segment: findings.observed.segment,
    window: findings.window,
    rows: findings.decomposition
      .filter((row) => Number.isFinite(row.share) && Number.isFinite(row.value))
      .slice()
      .sort((a, b) => Math.abs(b.share) - Math.abs(a.share)),
    explainedShare: findings.explained_share,
    unexplainedShare: findings.unexplained_share,
  };
}

export interface MetricInput {
  edge: string;
  node: string;
  kind: string;
  status: string;
  /** latest scored |z| of the input, null when the input is not scored hourly */
  z: number | null;
  /** median relative error of the latest relationship test */
  medianError: number | null;
}

/** The graph inputs of a metric, with the latest relationship test and the input's latest score. */
export function metricInputs(graph: Graph | null, view: RunView, metric: string): MetricInput[] {
  if (!graph || !metric) return [];
  const last = view.hours[view.hours.length - 1];
  const known = new Set(graph.nodes.map((node) => node.id));
  return graph.edges.filter((edge) => edge.target === metric && (edge.kind === "formula" || edge.kind === "cause")).flatMap((edge) => {
    const tested = view.edges[edge.id];
    const result = tested?.result ?? edge.last_test;
    return edge.sources.filter((source) => known.has(source)).map((node) => ({
      edge: edge.id,
      node,
      kind: edge.kind,
      status: tested?.status ?? edge.status,
      z: last ? peakOf(last, node) : null,
      medianError: result?.median_rel ?? null,
    }));
  });
}

export interface FunnelStage {
  node: string;
  /** the step-to-step rate from the previous stage into this one, when the graph defines it */
  rate: string | null;
  /** latest scored |z| of the stage count, null when it is not scored hourly */
  z: number | null;
  rateZ: number | null;
  anomalies: number;
  /** share of the latest recorded order change this step's rate explains */
  contribution: DriverRow | null;
}

export function funnelStages(graph: Graph | null, view: RunView, steps: readonly string[], window: AnalysisWindow, drivers: DriverDecomposition | null): FunnelStage[] {
  if (!graph) return [];
  const last = view.hours[view.hours.length - 1];
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  return steps.filter((id) => nodes.has(id)).map((node, index, present) => {
    const before = index ? present[index - 1] : null;
    const rate = before ? graph.nodes.find((candidate) => candidate.numerator === node && candidate.denominator === before)?.id ?? null : null;
    return {
      node,
      rate,
      z: last ? peakOf(last, node) : null,
      rateZ: last && rate ? peakOf(last, rate) : null,
      anomalies: view.anomalies.filter((a) => (a.node === node || a.node === rate) && inWindow(a.hour, window)).length,
      contribution: drivers?.rows.find((row) => row.node === rate || row.node === node) ?? null,
    };
  });
}
