import { describe, expect, it } from "vitest";
import { emptyView, type IncidentView } from "../../lib/store";
import type { Anomaly } from "../../lib/types";
import { DEFAULT_QUERY } from "../shell/query";
import { analysisIncidents, analysisSignals, analysisWindow, inWindow, matchesSegment } from "./model";

const incident: IncidentView = {
  id: "INC-0001", title: "Payments down", state: "resolved", verdict: "SUPPORTED_CAUSE",
  root_node: "payment_success_rate", segment: { platform: "android", country: "DE" },
  direction: "down", severity_eur: 15, change: "state", reason: "recovered", firstSeq: 5, lastSeq: 10,
  openedAt: "2026-11-20T22:00:00", updatedAt: "2026-11-22T00:00:00",
};
const signal: Anomaly = {
  id: "an_1", node: incident.root_node, segment: {}, direction: "down",
  hour: "2026-11-22T00:00:00", detected_at: "2026-11-22T00:00:00", onset: "2026-11-22T00:00:00",
  observed: 0.8, expected: 0.9, band: [0.89, 0.91], z: 5, rule: "z_gt_open", data_confidence: 1, receipts: [],
};

describe("active-stream analysis", () => {
  it("anchors a time window to the replay cursor in UTC and rejects future evidence", () => {
    const window = analysisWindow("2026-11-23T00:00:00", "24h");
    expect(inWindow("2026-11-22T00:00:00", window)).toBe(true);
    expect(inWindow("2026-11-22T00:00:00+00:00", window)).toBe(true);
    expect(inWindow("2026-11-21T23:59:59", window)).toBe(false);
    expect(inWindow("2026-11-23T00:00:01", window)).toBe(false);
    expect(inWindow("2026-11-22T00:00:00", analysisWindow(null, "all"))).toBe(false);
  });

  it("keeps open incidents and includes resolutions during the selected window", () => {
    const view = emptyView("replay-1", "replay");
    view.incidents = {
      [incident.id]: incident,
      active: { ...incident, id: "active", state: "monitoring", updatedAt: incident.openedAt },
      unseen: { ...incident, id: "unseen", updatedAt: "2026-11-23T10:00:00" },
    };
    const query = { ...DEFAULT_QUERY, segment: { country: "DE" }, metric: incident.root_node };
    expect(analysisIncidents(view, query, analysisWindow("2026-11-23T01:00:00", "24h")).map((i) => i.id)).toEqual(["active"]);
    expect(analysisIncidents(view, query, analysisWindow("2026-11-23T01:00:00", "7d")).map((i) => i.id)).toEqual(["active", incident.id]);
  });

  it("never treats a shop-wide observation as a scoped observation", () => {
    const view = emptyView("replay-1", "replay");
    view.anomalies = [signal];
    const query = { ...DEFAULT_QUERY, metric: signal.node };
    const window = analysisWindow(signal.hour, "24h");
    expect(analysisSignals(view, query, window)).toEqual([signal]);
    expect(analysisSignals(view, { ...query, segment: { country: "DE" } }, window)).toEqual([]);
    expect(matchesSegment(incident.segment, { country: "DE" })).toBe(true);
    expect(matchesSegment(incident.segment, { country: "FR" })).toBe(false);
  });
});
