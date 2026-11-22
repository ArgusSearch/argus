import { useMemo, type MouseEventHandler } from "react";
import { metricName, wherePhrase } from "../../fx/workspace/plain";
import { Card } from "../../fx/workspace/ui";
import type { RunView } from "../../lib/store";
import type { Graph, Incident, Segment } from "../../lib/types";
import { CountryDistribution } from "./CountryDistribution";
import { HistoricalMetrics } from "./HistoricalMetrics";
import { analyticsWindow, distributionRows, historyMarkers, historyPoints, measurementWindow, scopedIncidentChange, selectIncident, type AnalyticsPeriod, type AnalyticsQuery } from "./model";
import "./analytics.css";

export { CountryDistribution } from "./CountryDistribution";
export { HistoricalMetrics } from "./HistoricalMetrics";
export { ShopMetrics } from "./ShopMetrics";
export type { AnalyticsPeriod, AnalyticsQuery } from "./model";

export interface AnalyticsPanelsProps {
  graph: Graph | null;
  /** The active stream or the folded snapshot of the selected run. */
  view: RunView;
  /** Incident details from the same stream or run as view. */
  incidents: readonly Incident[];
  query: AnalyticsQuery;
  asOf?: string | null;
  incidentId?: string;
  incidentError?: string | null;
  onRetry?: () => void;
  onPeriodChange?: (period: AnalyticsPeriod) => void;
  segmentHref?: (segment: Segment) => string;
  incidentHref?: (id: string) => string;
  /** Lets the workspace follow links without reloading the active run. */
  onNavigate?: MouseEventHandler<HTMLAnchorElement>;
  section?: "history" | "distribution" | "both";
}

export function AnalyticsPanels({
  graph, view, incidents, query, asOf = view.simTs, incidentId, incidentError, onRetry, onPeriodChange,
  segmentHref, incidentHref, onNavigate, section = "both",
}: AnalyticsPanelsProps) {
  const metric = graph?.nodes.find(({ id }) => id === query.metric);
  const scope = wherePhrase(query.segment);
  const window = useMemo(() => analyticsWindow(asOf, query.period), [asOf, query.period]);
  const incident = useMemo(() => selectIncident(view, incidents, query, window, incidentId), [view, incidents, query, window, incidentId]);
  const points = useMemo(() => historyPoints(view, query, window, incident), [view, query, window, incident]);
  const markers = useMemo(() => historyMarkers(incident, window), [incident, window]);
  const measurement = measurementWindow(view, incident);

  if (!metric) {
    return <Card title="Analytics" className="an-card"><p className="fx-empty">
      {graph ? (query.metric ? `No data for ${metricName(graph, query.metric)}.` : "Select a metric to view its history and segments.") : "Waiting for the metric graph."}
    </p></Card>;
  }
  const denominator = graph?.nodes.find(({ id }) => id === metric.denominator)?.label;
  const volumeBasis = metric.kind === "ratio" ? `current ${denominator?.toLocaleLowerCase("en") ?? "denominator"}` : "expected metric volume";
  return (
    <>
      {incidentError && (
        <p className="an-state" role="status">
          {incidentError} {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
        </p>
      )}
      <div className="an-panels" data-layout={section}>
        {section !== "distribution" && (
          <HistoricalMetrics metric={metric} scope={scope} period={query.period} window={window} points={points} markers={markers}
            incident={incident} change={scopedIncidentChange(incident, query, window, measurement)} onPeriodChange={onPeriodChange}
            incidentHref={incidentHref} onNavigate={onNavigate} stream={view.stream} />
        )}
        {section !== "history" && (
          <CountryDistribution metric={metric} scope={scope} rows={distributionRows(incident, metric, window, query.segment, measurement)}
            incident={incident} measurement={measurement} volumeBasis={volumeBasis} segmentHref={segmentHref} incidentHref={incidentHref}
            onNavigate={onNavigate} />
        )}
      </div>
    </>
  );
}
