import { describe, expect, it } from "vitest";
import { emptyView, type HourStat, type IncidentView, type RunView } from "../../lib/store";
import type { Anomaly, Graph, Incident } from "../../lib/types";
import {
  compareRecent, deviationHistory, driverDecomposition, funnelStages, hourlyTrend, incidentCohorts, metricInputs, segmentBreakdown,
} from "./model";

const hour = (h: number, byNode: Record<string, number>, open = 0, completeness = 1): HourStat => ({
  hour: new Date(Date.UTC(2026, 10, 20, h)).toISOString().slice(0, 19),
  z: Object.values(byNode),
  byNode,
  open,
  eur: 0,
  completeness,
});

const anomaly = (id: string, node: string, h: number, segment: Record<string, string>, z = -6, direction: "up" | "down" = "down"): Anomaly => ({
  id, node, segment, direction, hour: new Date(Date.UTC(2026, 10, 20, h)).toISOString().slice(0, 19), detected_at: "", onset: "",
  observed: 1, expected: 2, band: [1.5, 2.5], z, rule: "z_gt_open", data_confidence: 1, receipts: [],
});

const incident = (id: string, openedH: number, updatedH: number, state: IncidentView["state"], severity: number, segment: Record<string, string> = {}): IncidentView => ({
  id, title: id, state, verdict: "SUPPORTED_CAUSE", root_node: "payment_success_rate", segment, direction: "down", severity_eur: severity,
  change: "state", reason: "", firstSeq: 1, lastSeq: 2,
  openedAt: new Date(Date.UTC(2026, 10, 20, openedH)).toISOString().slice(0, 19),
  updatedAt: new Date(Date.UTC(2026, 10, 20, updatedH)).toISOString().slice(0, 19),
});

function view(hours: HourStat[], extra: Partial<RunView> = {}): RunView {
  return { ...emptyView("s", "replay"), hours, ...extra };
}

const all = { start: null, end: Date.UTC(2026, 10, 30) };

describe("hourlyTrend", () => {
  it("reads the per-hour peak and threshold counts, for all metrics or one", () => {
    const v = view([hour(0, { a: 1, b: 3 }), hour(1, { a: 6, b: 0.5 }, 1)]);
    const points = hourlyTrend(v.hours, v.thresholds, all);
    expect(points.map((p) => [p.peak, p.watch, p.alarm, p.open])).toEqual([[3, 1, 0, 0], [6, 0, 1, 1]]);
    expect(hourlyTrend(v.hours, v.thresholds, all, "b").map((p) => p.peak)).toEqual([3, 0.5]);
    expect(hourlyTrend(v.hours, v.thresholds, all, "missing").map((p) => p.peak)).toEqual([null, null]);
  });
});

describe("compareRecent", () => {
  it("compares the latest span with the span before and leaves the previous period empty without history", () => {
    const hours = [hour(0, { a: 6 }), hour(1, { a: 1 }), hour(2, { a: 2 }), hour(3, { a: 1 })];
    const v = view(hours, { anomalies: [anomaly("x", "a", 0, {})], incidents: { i: incident("i", 0, 1, "open", 10) } });
    const result = compareRecent(v, "", {}, 2)!;
    expect(result.current).toMatchObject({ hours: 2, peak: 2, watchHours: 1, alarmHours: 0, anomalies: 0 });
    expect(result.previous).toMatchObject({ hours: 2, peak: 6, alarmHours: 1, anomalies: 1, incidentsOpened: 1 });
    expect(compareRecent(view([hour(0, { a: 1 })]), "", {}, 2)!.previous).toBeNull();
    expect(compareRecent(view([]), "", {})).toBeNull();
  });
});

describe("deviationHistory", () => {
  it("orders rows, marks anomaly hours and leaves unscored cells empty", () => {
    const v = view([hour(0, { a: 1, b: 2 }), hour(1, { b: 7 })], { anomalies: [anomaly("x", "b", 1, { country: "DE" })] });
    const { columns, rows } = deviationHistory(v, all, ["b"]);
    expect(columns).toHaveLength(2);
    expect(rows.map((r) => r.metric)).toEqual(["b", "a"]);
    expect(rows[0].cells.map((c) => c.flagged)).toEqual([false, true]);
    expect(rows[1].cells[1].z).toBeNull();
    expect(rows[0]).toMatchObject({ peak: 7, anomalies: 1 });
    expect(deviationHistory(v, all, [], ["a"]).rows.map((r) => r.metric)).toEqual(["a"]);
  });
});

describe("segmentBreakdown", () => {
  it("counts every dimension of a scope and sums incident impact", () => {
    const { rows, wholeShop } = segmentBreakdown(
      [anomaly("1", "a", 0, { country: "DE", platform: "android" }), anomaly("2", "a", 1, { country: "DE" }, 4, "up"), anomaly("3", "a", 2, {})],
      [incident("i", 0, 1, "open", -500, { country: "DE" })],
    );
    expect(wholeShop).toBe(1);
    expect(rows.find((r) => r.value === "DE")).toMatchObject({ anomalies: 2, falls: 1, rises: 1, incidents: 1, impact: 500, peakZ: 6 });
    expect(rows.find((r) => r.value === "android")).toMatchObject({ anomalies: 1, incidents: 0, impact: 0 });
  });
});

describe("incidentCohorts", () => {
  it("groups by opening day with current states and the mean time to resolve", () => {
    const rows = incidentCohorts([incident("a", 1, 5, "resolved", 100), incident("b", 2, 3, "explained", -50), incident("c", 30, 31, "open", 1)]);
    expect(rows).toEqual([
      { day: "2026-11-21", opened: 1, active: 1, explained: 0, resolved: 0, impact: 1, hoursToResolve: null },
      { day: "2026-11-20", opened: 2, active: 0, explained: 1, resolved: 1, impact: 150, hoursToResolve: 4 },
    ]);
  });
});

const graph = {
  nodes: [
    { id: "sessions", label: "Visits", table: "sessions", numerator: null, denominator: null },
    { id: "orders", label: "Orders", table: "orders", numerator: null, denominator: null },
    { id: "cvr", label: "Conversion", table: null, numerator: "orders", denominator: "sessions" },
  ],
  edges: [{ id: "f_orders", kind: "formula", target: "orders", sources: ["sessions", "cvr"], status: "VALID", last_test: { median_rel: 0.01 } }],
} as unknown as Graph;

const findings = (id: string, updated: string, node: string | null) => ({
  id, updated_at: updated,
  findings: {
    decomposed_node: node, observed: { node: "payment_success_rate", segment: {} }, root: null, window: { start: "x", end: "x" },
    decomposition: node ? [{ node: "sessions", share: 0.2, value: -5, receipt: null }, { node: "cvr", share: 0.8, value: -20, receipt: "r1" }] : [],
    explained_share: 1, unexplained_share: 0,
  },
}) as unknown as Incident;

describe("driver decomposition, inputs and funnel", () => {
  it("picks the latest decomposition, sorted by share", () => {
    const drivers = driverDecomposition([findings("A", "2026-11-20T01:00:00", "orders"), findings("B", "2026-11-20T03:00:00", "orders"), findings("C", "2026-11-21T00:00:00", null)])!;
    expect(drivers.incidentId).toBe("B");
    expect(drivers.rows.map((r) => r.node)).toEqual(["cvr", "sessions"]);
    expect(driverDecomposition([findings("A", "2026-11-20T01:00:00", "orders")], "gmv")).toBeNull();
  });

  it("lists graph inputs with their latest score and test", () => {
    const v = view([hour(0, { sessions: 1.2 })]);
    expect(metricInputs(graph, v, "orders")).toEqual([
      { edge: "f_orders", node: "sessions", kind: "formula", status: "VALID", z: 1.2, medianError: 0.01 },
      { edge: "f_orders", node: "cvr", kind: "formula", status: "VALID", z: null, medianError: 0.01 },
    ]);
  });

  it("finds each step's rate and its share of the order change", () => {
    const drivers = driverDecomposition([findings("A", "2026-11-20T01:00:00", "orders")]);
    const stages = funnelStages(graph, view([hour(0, { orders: 2 })]), ["sessions", "orders"], all, drivers);
    expect(stages.map((s) => [s.node, s.rate, s.z, s.contribution?.node ?? null])).toEqual([
      ["sessions", null, null, "sessions"],
      ["orders", "cvr", 2, "cvr"],
    ]);
  });
});
