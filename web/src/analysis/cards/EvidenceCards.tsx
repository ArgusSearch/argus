import type { ReactNode } from "react";
import { metricName, wherePhrase } from "../../fx/workspace/plain";
import { useIncidents } from "../../fx/workspace/ui";
import { dayLabel, hhmm } from "../../lib/format";
import type { IncidentView, RunView } from "../../lib/store";
import type { Anomaly, Graph } from "../../lib/types";
import { time, visibleIncident } from "../analytics/model";
import { DistributionCard, MetricBarsCard, TickRingCard } from "./AnalysisCards";
import { anomalyPoints, graphUnit, incidentBars, incidentMarker, relativeChange } from "./evidence";
import { MetricTrendCard } from "./MetricTrendCard";
import { timestamp, validValue, type DistributionSlice } from "./model";

interface EvidenceCardsProps {
  view: RunView;
  graph: Graph | null;
  graphFailed?: boolean;
  metricId: string;
  observations: readonly Anomaly[];
  statuses: readonly IncidentView[];
  renderReceipt: (id: string | undefined, label: string) => ReactNode;
}

export function EvidenceCards({ view, graph, graphFailed, metricId, observations, statuses, renderReceipt }: EvidenceCardsProps) {
  const { incidents, failed } = useIncidents(view);
  const unit = graphUnit(graph?.nodes.find((node) => node.id === metricId)?.unit);
  const anchor = observations.reduce<Anomaly | undefined>((latest, observation) =>
    !latest || timestamp(observation.hour) > timestamp(latest.hour) ? observation : latest, undefined);
  const window = { start: null, end: time(view.simTs) };
  const incident = incidents.find((candidate) => candidate.findings.anomaly_id === anchor?.id && visibleIncident(view, candidate, window));
  const title = metricName(graph, metricId);
  const context = anchor
    ? `${Object.keys(anchor.segment).length ? wherePhrase(anchor.segment) : "Whole shop"} · ${dayLabel(anchor.hour)}, ${hhmm(anchor.hour)} UTC`
    : undefined;
  const empty = graphFailed || (anchor && !unit) ? "Metric definition unavailable." : "No scored observation in this scope.";
  const marker = incidentMarker(incident, view.simTs);
  const drill = anchor && unit ? incidentBars(anchor, incident, unit) : null;
  const change = anchor && unit ? relativeChange(anchor, unit) : null;
  const observed = anchor && unit === "share" ? anchor.observed : null;
  const expected = anchor && unit === "share" && validValue(anchor.expected, unit)
    ? { share: anchor.expected, label: "Expected" }
    : undefined;
  const slices: DistributionSlice[] = [
    { id: "resolved", label: "Resolved", count: statuses.filter((entry) => entry.state === "resolved").length, tone: "green" },
    { id: "recovering", label: "Recovering", count: statuses.filter((entry) => entry.state === "monitoring").length, tone: "blue" },
    { id: "open", label: "Open", count: statuses.filter((entry) => entry.state !== "resolved" && entry.state !== "monitoring").length, tone: "amber" },
  ];

  return (
    <div className="ac-evidence-grid">
      <MetricBarsCard
        title={`${title} by scope`}
        context={context}
        metric={anchor && unit ? { value: anchor.observed, unit } : undefined}
        change={change === null ? undefined : {
          value: change, unit: "pct", basis: "vs expected", tone: change < 0 ? "red" : change > 0 ? "green" : "neutral",
        }}
        unit="pct"
        bars={drill?.bars ?? []}
        hatchLabel="Nested scopes · vs expected"
        empty={empty}
        footer={(failed || anchor) && <>
          {renderReceipt(anchor?.receipts[0], "Observation receipt")}
          {failed ? "Incident evidence unavailable" : renderReceipt(drill?.receipt, "Segment receipt")}
        </>}
      />
      {(!unit || unit === "share") && <TickRingCard
        title={title}
        context={context}
        share={observed}
        benchmark={expected}
        empty={empty}
        footer={anchor && renderReceipt(anchor.receipts[0], "Observation receipt")}
      />}
      <MetricTrendCard
        title={`${title} observations`}
        context={anchor ? `${Object.keys(anchor.segment).length ? wherePhrase(anchor.segment) : "Whole shop"} · Scored anomalies` : undefined}
        unit={unit ?? "value"}
        points={anchor && unit ? anomalyPoints(observations, anchor) : []}
        event={marker}
        empty={empty}
        footer={anchor && <>
          {renderReceipt(anchor.receipts[0], "Observation receipt")}
          {renderReceipt(marker?.receipt, "Event receipt")}
        </>}
      />
      <DistributionCard
        title="Incident states"
        context="Matching incidents"
        total={statuses.length}
        totalLabel={statuses.length === 1 ? "incident" : "incidents"}
        slices={slices}
        empty={view.simTs ? "No incidents match this scope." : "Waiting for run data."}
      />
    </div>
  );
}
