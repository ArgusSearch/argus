import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import recordedAnomalies from "../../../../fixtures/anomalies.json?raw";
import recordedGraph from "../../../../fixtures/graph.json?raw";
import recordedIncidents from "../../../../fixtures/incidents.json?raw";
import type { Anomaly, Graph, Incident } from "../../lib/types";
import { anomalyPoints, graphUnit, incidentBars, incidentMarker, relativeChange } from "./evidence";
import { DistributionCard, MetricBarsCard, MetricTrendCard, TickRingCard } from "./index";
import { chartPoints, distributionTotal, formatPortion, formatValue, runs, timestamp } from "./model";

const [incident] = JSON.parse(recordedIncidents) as Incident[];
const [anchor] = JSON.parse(recordedAnomalies) as Anomaly[];
const graph = JSON.parse(recordedGraph) as Graph;
const hour = 60 * 60 * 1000;
const slices = [
  { id: "done", label: "Resolved", count: 3, tone: "green" as const },
  { id: "open", label: "Open", count: 1, tone: "amber" as const },
];

describe("analysis card data", () => {
  it("keeps missing data, observed zero, shares and distinct delta units", () => {
    expect(formatValue(null, "count")).toBe("—");
    expect(formatValue(0, "count")).toBe("0");
    expect(formatValue(0.924902, "share")).toBe("92.5%");
    expect(formatValue(92.5, "share")).toBe("—");
    expect(formatValue(-2.4, "pct")).toBe("-2.4%");
    expect(formatValue(2.4, "pp", true)).toBe("+2.4 pp");
    expect(formatValue(3.4, "ratio")).toBe("3.4×");
    expect(formatValue(2.4, "eur_per_unit")).toBe("€2.40");
    expect(formatPortion(0.9999)).toBe(">99.9%");
    expect(formatPortion(0.0001)).toBe("<0.1%");
  });

  it("requires a reconciled, disjoint count partition", () => {
    expect(distributionTotal(slices, 4)).toBe(4);
    expect(distributionTotal(slices, 5)).toBeNull();
    expect(distributionTotal([slices[0], slices[0]], 6)).toBeNull();
    expect(distributionTotal([{ ...slices[0], count: 1.5 }], 1.5)).toBeNull();
    expect(distributionTotal([{ ...slices[0], count: -1 }, slices[1]], 0)).toBeNull();
    expect(distributionTotal([], 0)).toBeNull();
  });

  it("orders UTC samples and splits missing or distant readings", () => {
    const first = "2026-11-21T18:00:00";
    const samples = chartPoints([
      { at: "2026-11-21T21:00:00Z", observed: 0.91, band: [0.94, 0.93] },
      { at: "2026-11-21T19:00:00Z", observed: 0 },
      { at: first, observed: 0.85 },
      { at: "2026-11-21T22:00:00+01:00", observed: 0.93, band: [0.93, 0.95] },
      { at: "2026-11-21T22:00:00Z", observed: null },
      { at: "2026-11-21T23:00:00Z", observed: 0.96 },
      { at: "unknown", observed: 0.95 },
    ], "share");
    expect(samples[0].time).toBe(timestamp(`${first}Z`));
    expect(samples[2].band).toEqual([0.93, 0.95]);
    expect(runs(samples.map(({ observed, time }) => ({ time, value: observed })), hour)
      .map((group) => group.map(({ value }) => value))).toEqual([[0.85, 0], [0.93], [0.96]]);
  });

  it("uses S1 graph units, exact scopes and recorded nested changes", () => {
    expect(anchor.node).toBe("payment_success_rate");
    const unit = graphUnit(graph.nodes.find((node) => node.id === anchor.node)?.unit);
    expect(unit).toBe("share");
    expect(graphUnit("unknown")).toBeNull();
    expect(anomalyPoints([anchor, { ...anchor, segment: { country: "DE" } }], anchor)).toEqual([{
      at: anchor.hour, observed: anchor.observed, expected: anchor.expected, band: anchor.band,
    }]);
    expect(relativeChange({ ...anchor, expected: 0 }, "share")).toBeNull();
    const drill = incidentBars(anchor, incident, "share");
    expect(drill.bars.map((bar) => formatValue(bar.value, "pct"))).toEqual(["-2.4%", "-7.5%", "-18.5%", "-36.4%"]);
    expect(drill.receipt).toBeTruthy();
    expect(incidentBars({ ...anchor, segment: { country: "FR" } }, incident, "share").bars).toHaveLength(1);
  });

  it("labels the refuted S1 release and gates marker timestamps to the current cursor", () => {
    expect(incidentMarker(incident, incident.updated_at)).toMatchObject({
      at: "2026-11-21T17:54:00", label: "Release ruled out", receipt: "r240",
    });
    expect(incidentMarker(incident, "2026-11-21T17:50:00")).toBeUndefined();
  });
});

describe("analysis card markup", () => {
  it("renders a band and accessible table with the one observed bucket", () => {
    const markup = renderToStaticMarkup(<MetricTrendCard
      title="Payment observations"
      unit="share"
      points={anomalyPoints([anchor], anchor)}
      event={incidentMarker(incident, incident.updated_at)}
    />);
    expect(markup).toContain("One observed time bucket.");
    expect(markup).toContain("Release ruled out");
    expect(markup).toContain('role="tooltip"');
    expect(markup).toContain("94.3% – 95.3%");
    expect(markup).toContain('class="ac-point"');
    expect(markup).not.toContain('class="ac-area"');
  });

  it("shows the filled trend and distinct expected path for adjacent samples", () => {
    const markup = renderToStaticMarkup(<MetricTrendCard
      title="Counts"
      unit="count"
      maxGapMs={hour}
      points={[
        { at: "2026-11-21T17:00:00Z", observed: 0, expected: 2, band: [1, 3] },
        { at: "2026-11-21T18:00:00Z", observed: 1, expected: 2, band: [0, 3] },
        { at: "2026-11-21T20:00:00Z", observed: 3, expected: 4 },
      ]}
    />);
    expect(markup.match(/class="ac-area"/g)).toHaveLength(1);
    expect(markup.match(/class="ac-observed"/g)).toHaveLength(1);
    expect(markup.match(/class="ac-point"/g)).toHaveLength(1);
    expect(markup).toContain('<td>0</td>');
  });

  it("exposes zero values and leaves missing or inconsistent data empty", () => {
    const bars = [{ id: "zero", label: "Sample A", value: 0 }, { id: "missing", label: "Sample B", value: null }];
    expect(renderToStaticMarkup(<MetricBarsCard bars={bars} unit="count" title="Counts" />)).toContain("No value");
    expect(renderToStaticMarkup(<TickRingCard title="Rate" share={0} />)).toContain("0%");
    expect(renderToStaticMarkup(<TickRingCard title="Rate" share={null} />)).toContain("No observations in this scope.");
    expect(renderToStaticMarkup(<DistributionCard title="Incidents" slices={slices} total={4} totalLabel="incidents" />)).toContain("75%");
    expect(renderToStaticMarkup(<DistributionCard title="Incidents" slices={slices} total={8} totalLabel="incidents" />)).toContain("No complete distribution for this scope.");
  });
});
