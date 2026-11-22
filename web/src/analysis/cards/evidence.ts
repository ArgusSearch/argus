import { whereCells, wherePhrase } from "../../fx/workspace/plain";
import type { Anomaly, Incident, Segment } from "../../lib/types";
import type { BarValue } from "./AnalysisCards";
import { timestamp, validValue, type CardUnit, type ChartEvent, type ChartPoint } from "./model";

function scopeMatches(a: Segment, b: Segment): boolean {
  return Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([key, value]) => b[key] === value);
}

function asSegment(value: unknown): Segment | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return Object.values(value).every((item) => typeof item === "string") ? value as Segment : null;
}

export function graphUnit(value: string | undefined): CardUnit | null {
  switch (value) {
    case "share": case "eur": case "eur_per_unit": case "count": case "hours": case "pct": case "pp": case "ratio": case "value":
      return value;
    default:
      return null;
  }
}

export function anomalyPoints(anomalies: readonly Anomaly[], anchor: Anomaly): ChartPoint[] {
  const byHour = new Map<string, ChartPoint>();
  for (const anomaly of anomalies) {
    if (anomaly.node === anchor.node && scopeMatches(anomaly.segment, anchor.segment)) {
      byHour.set(anomaly.hour, {
        at: anomaly.hour, observed: anomaly.observed, expected: anomaly.expected, band: anomaly.band,
      });
    }
  }
  return [...byHour.values()];
}

export function relativeChange(anchor: Anomaly, unit: CardUnit): number | null {
  if (!validValue(anchor.observed, unit) || !validValue(anchor.expected, unit) || anchor.expected <= 0) return null;
  const change = 100 * (anchor.observed - anchor.expected) / anchor.expected;
  return Number.isFinite(change) ? change : null;
}

export function incidentBars(anchor: Anomaly, incident: Incident | undefined, unit: CardUnit): { bars: BarValue[]; receipt?: string } {
  const bars: BarValue[] = [{
    id: "observed-scope",
    label: Object.keys(anchor.segment).length ? whereCells(anchor.segment).map((cell) => cell.value).join(" · ") : "Whole shop",
    value: relativeChange(anchor, unit),
  }];
  const drill = incident?.findings.trail.find((step) => step.tool === "segment_search");
  const start = asSegment(drill?.data.start);
  if (incident?.findings.anomaly_id !== anchor.id || !start || !scopeMatches(start, anchor.segment) || !Array.isArray(drill?.data.path)) {
    return { bars };
  }

  let previous = start;
  for (const point of drill.data.path) {
    const segment = asSegment(point?.segment);
    const change = point?.rel_change;
    if (!segment || Object.keys(segment).length <= Object.keys(previous).length
      || !Object.entries(previous).every(([key, value]) => segment[key] === value)
      || typeof change !== "number" || !Number.isFinite(change * 100)) break;
    bars.push({
      id: JSON.stringify(Object.entries(segment).sort()),
      label: whereCells(segment).map((cell) => cell.value).join(" · "),
      value: change * 100,
      hatched: true,
    });
    previous = segment;
  }
  return { bars, receipt: bars.length > 1 ? drill.receipts[0] : undefined };
}

export function incidentMarker(incident: Incident | undefined, asOf: string | null): (ChartEvent & { receipt?: string }) | undefined {
  if (!incident || !asOf) return;
  const visible = (at: string) => timestamp(at) <= timestamp(asOf);
  const release = incident.findings.ruled_out.find((hypothesis) =>
    hypothesis.result === "refuted" && hypothesis.evidence?.kind === "release" && visible(hypothesis.evidence.ts));
  if (release?.evidence) {
    return {
      at: release.evidence.ts,
      label: "Release ruled out",
      detail: `${release.evidence.description}. ${release.reason}`,
      receipt: release.receipts[0],
    };
  }
  const root = incident.findings.root;
  const log = root?.evidence;
  if (incident.verdict === "SUPPORTED_CAUSE" && log && visible(log.ts)) {
    return {
      at: log.ts,
      label: "Supported event",
      detail: `${log.description}. Affected scope: ${wherePhrase(root.segment)}.`,
      receipt: root.change_pct.receipt ?? undefined,
    };
  }
}
