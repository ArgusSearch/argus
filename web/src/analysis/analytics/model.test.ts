import { describe, expect, it } from "vitest";
import eventFixture from "../../../../fixtures/events.jsonl?raw";
import graphFixture from "../../../../fixtures/graph.json?raw";
import incidentFixture from "../../../../fixtures/incidents.json?raw";
import { emptyView, foldAll } from "../../lib/store";
import type { ArgusEvent, Graph, Incident } from "../../lib/types";
import { analyticsWindow, distributionRows, historyMarkers, historyPoints, measurementWindow, metricValue, scopedIncidentChange, selectIncident, time } from "./model";

const [incident] = JSON.parse(incidentFixture) as Incident[];
const graph = JSON.parse(graphFixture) as Graph;
const events = eventFixture.trim().split("\n").map((line) => JSON.parse(line) as ArgusEvent);
const view = foldAll(emptyView("s1", "replay"), events);
const metric = graph.nodes.find(({ id }) => id === "payment_success_rate")!;
const shop = { metric: metric.id, segment: {}, period: "30d" as const };
const window = analyticsWindow(view.simTs, shop.period);
const measurement = measurementWindow(view, incident);

describe("S1 analytics evidence", () => {
  it("plots only the actual shop-wide sample with the matching dated expectation and receipt", () => {
    expect(historyPoints(view, shop, window, incident)).toEqual([{
      at: time("2026-11-21T18:00:00"),
      observed: 0.924902,
      expected: 0.94769,
      band: [0.942787, 0.952619],
      receipts: ["r225"],
    }]);
    expect(historyPoints(view, { ...shop, segment: incident.segment }, window, incident)).toEqual([]);
  });

  it("respects period and as-of bounds on both sample and discovery timestamps", () => {
    expect(historyPoints(view, shop, analyticsWindow(view.simTs, "24h"), incident)).toEqual([]);
    expect(historyPoints(view, shop, analyticsWindow("2026-11-21T19:00:00", "all"))).toEqual([]);
    const open = analyticsWindow("2026-11-21T20:00:00", "all");
    expect(historyPoints(view, shop, open)).toHaveLength(1);
    expect(analyticsWindow(null, "1y")).toEqual({ start: null, end: null });
  });

  it("waits for a matching incident version at the active clock", () => {
    // The replay API timestamps incident snapshots with the publishing event.
    const published = { ...incident, updated_at: view.incidents[incident.id].updatedAt };
    expect(selectIncident(view, [published], shop, window)?.id).toBe(incident.id);
    expect(selectIncident(emptyView("another", "replay"), [published], shop, window)).toBeUndefined();
    expect(selectIncident(view, [published], shop, analyticsWindow("2026-11-21T20:00:00", "all"))).toBeUndefined();
    expect(selectIncident(view, [{ ...published, state: "monitoring" }], shop, window)).toBeUndefined();
  });

  it("uses each row's measured change, parent volume and query receipt without summing nested scopes", () => {
    const rows = distributionRows(incident, metric, window, {}, measurement);
    expect(rows.map(({ segment, parent, change, volumeShare, receipts }) => [segment, parent, change, volumeShare, receipts])).toEqual([
      [{ country: "DE" }, {}, -0.0755, 0.3402, ["r230"]],
      [{ country: "DE", platform: "android" }, { country: "DE" }, -0.1851, 0.4127, ["r234"]],
      [incident.segment, { country: "DE", platform: "android" }, -0.364, 0.4904, ["r236"]],
    ]);
    expect(distributionRows(incident, metric, window, incident.segment, measurement)).toEqual([rows[2]]);
    expect(distributionRows(incident, metric, window, { country: "FR" }, measurement)).toEqual([]);
    expect(distributionRows(incident, metric, analyticsWindow(view.simTs, "24h"), {}, measurement)).toEqual([]);
  });

  it("uses the original measurement window and supports older paths without an explicit search start", () => {
    const older = {
      ...incident,
      findings: {
        ...incident.findings,
        window: { ...incident.findings.window, start: "2026-11-21T14:00:00" },
        trail: incident.findings.trail.map((step) => ({ ...step, data: { ...step.data, start: undefined } })),
      },
    };
    const search = measurementWindow(view, older);
    expect(search).toEqual(incident.findings.window);
    const recent = analyticsWindow("2026-11-22T17:00:00", "24h");
    expect(distributionRows(older, metric, recent, {}, search)).toHaveLength(3);
  });

  it("anchors incident and release markers to recorded times and preserves the release verdict", () => {
    const markers = historyMarkers(incident, window);
    expect(markers).toContainEqual(expect.objectContaining({ kind: "incident", at: time(incident.opened_at) }));
    expect(markers).toContainEqual(expect.objectContaining({
      id: "dep_android-app_8.3.0", at: time("2026-11-21T17:54:00"), label: "Release ruled out", receipts: ["r240"],
    }));
    expect(historyMarkers(incident, analyticsWindow(view.simTs, "24h"))).toEqual([]);
    const beforeChecks = { ...incident, findings: { ...incident.findings, trail: incident.findings.trail.filter(({ tool }) => tool === "list_events") } };
    expect(historyMarkers(beforeChecks, window)).toContainEqual(expect.objectContaining({
      id: "dep_android-app_8.3.0", label: "Release checked", receipts: ["r238"],
    }));
  });

  it("shows the receipt-backed root change only for the exact root scope", () => {
    expect(scopedIncidentChange(incident, shop, window, measurement)).toBeNull();
    const root = { ...shop, segment: incident.segment };
    expect(scopedIncidentChange(incident, root, window, measurement)).toEqual(incident.findings.root?.change_pct);
    expect(scopedIncidentChange(incident, root, analyticsWindow(view.simTs, "24h"), measurement)).toBeNull();
  });

  it("preserves the distinction between shares, relative changes and multiples", () => {
    expect(metricValue(0.924902, "share")).toBe("92.5%");
    expect(metricValue(-2.4, "pct")).toBe("-2.4%");
    expect(metricValue(1.995, "ratio")).toBe("1.995×");
  });
});
