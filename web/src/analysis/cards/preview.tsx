import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "../../styles.css";
import "../../fx/tokens.css";
import { metricName, wherePhrase } from "../../fx/workspace/plain";
import { useIncidents } from "../../fx/workspace/ui";
import { api, follow, type ConnectionState } from "../../lib/api";
import { apiUrl } from "../../lib/deployment";
import { dayLabel, hhmm } from "../../lib/format";
import { emptyView, foldAll, type RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import {
  anomalyPoints, DistributionCard, graphUnit, incidentBars, incidentMarker, MetricBarsCard, MetricTrendCard,
  relativeChange, TickRingCard, type DistributionSlice,
} from "./index";
import { timestamp, validValue } from "./model";
import "./preview.css";

const metricId = "payment_success_rate";

function ReceiptLink({ id, label }: { id?: string; label: string }) {
  return id && <a href={apiUrl(`/receipts/${encodeURIComponent(id)}`)}>{label}</a>;
}

function Cards({ view, graph, graphFailed }: { view: RunView; graph: Graph | null; graphFailed: boolean }) {
  const { incidents, failed } = useIncidents(view);
  const unit = graphUnit(graph?.nodes.find((node) => node.id === metricId)?.unit);
  const anchor = view.anomalies.findLast((anomaly) => anomaly.node === metricId);
  const incident = incidents.find((candidate) => {
    const current = view.incidents[candidate.id];
    return candidate.findings.anomaly_id === anchor?.id && current?.state === candidate.state
      && view.simTs && timestamp(candidate.updated_at) <= timestamp(view.simTs);
  });
  const title = metricName(graph, metricId);
  const context = anchor
    ? `${Object.keys(anchor.segment).length ? wherePhrase(anchor.segment) : "Whole shop"} · ${dayLabel(anchor.hour)}, ${hhmm(anchor.hour)} UTC`
    : undefined;
  const empty = graphFailed || (anchor && !unit) ? "Metric definition unavailable." : "No payment observation in this stream.";
  const marker = incidentMarker(incident, view.simTs);
  const drill = anchor && unit ? incidentBars(anchor, incident, unit) : null;
  const change = anchor && unit ? relativeChange(anchor, unit) : null;
  const observed = anchor && unit === "share" ? anchor.observed : null;
  const expected = anchor && unit === "share" && validValue(anchor.expected, unit)
    ? { share: anchor.expected, label: "Expected" }
    : undefined;
  const statuses = Object.values(view.incidents);
  const slices: DistributionSlice[] = [
    { id: "resolved", label: "Resolved", count: statuses.filter((entry) => entry.state === "resolved").length, tone: "green" },
    { id: "recovering", label: "Recovering", count: statuses.filter((entry) => entry.state === "monitoring").length, tone: "blue" },
    { id: "open", label: "Open", count: statuses.filter((entry) => entry.state !== "resolved" && entry.state !== "monitoring").length, tone: "amber" },
  ];

  return (
    <div className="ac-preview-grid">
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
          <ReceiptLink id={anchor?.receipts[0]} label="Observation receipt" />
          {failed ? "Incident evidence unavailable" : <ReceiptLink id={drill?.receipt} label="Segment receipt" />}
        </>}
      />
      <TickRingCard
        title={title}
        context={context}
        share={observed}
        benchmark={expected}
        empty={empty}
        footer={anchor && <ReceiptLink id={anchor.receipts[0]} label="Observation receipt" />}
      />
      <MetricTrendCard
        title={`${title} observations`}
        context={anchor ? `${Object.keys(anchor.segment).length ? wherePhrase(anchor.segment) : "Whole shop"} · Scored anomalies` : undefined}
        unit={unit ?? "value"}
        points={anchor && unit ? anomalyPoints(view.anomalies, anchor) : []}
        event={marker}
        empty={empty}
        footer={anchor && <>
          <ReceiptLink id={anchor.receipts[0]} label="Observation receipt" />
          <ReceiptLink id={marker?.receipt} label="Event receipt" />
        </>}
      />
      <DistributionCard
        title="Incident states"
        context="Current stream"
        total={statuses.length}
        totalLabel={statuses.length === 1 ? "incident" : "incidents"}
        slices={slices}
        empty="No incidents recorded in this stream."
      />
    </div>
  );
}

function Preview() {
  const [view, setView] = useState(emptyView);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [graphFailed, setGraphFailed] = useState(false);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    let version = 0;
    const stop = follow({
      onState: setConnection,
      onReset: ({ stream, mode }) => {
        const request = ++version;
        setView(emptyView(stream, mode));
        setGraph(null);
        setGraphFailed(false);
        void api.graph().then(
          (next) => { if (active && version === request) setGraph(next); },
          () => { if (active && version === request) setGraphFailed(true); },
        );
      },
      onEvents: (events) => setView((current) => foldAll(current, events)),
    });
    return () => {
      active = false;
      stop();
    };
  }, [attempt]);

  const asOf = view.simTs && `${dayLabel(view.simTs)}, ${hhmm(view.simTs)} UTC`;
  const status = connection === "connecting" ? "Connecting to Argus…"
    : connection === "offline" ? (asOf ? "Connection lost. Showing the last received data." : "Argus API unavailable.")
    : graphFailed ? "Could not load metric definitions."
    : view.mode && (view.mode === "replay" ? "Recorded replay" : "Live stream");

  return (
    <main className="ac-preview">
      <header className="ac-preview-header">
        <h1>Analysis cards</h1>
        <div className="ac-preview-status">
          <p role="status">{status}{asOf && ` · As of ${asOf}`}</p>
          {(connection === "offline" || graphFailed) &&
            <button type="button" onClick={() => setAttempt((current) => current + 1)}>Retry connection</button>}
        </div>
      </header>
      {view.stream && (graph || graphFailed) && <Cards key={view.stream} view={view} graph={graph} graphFailed={graphFailed} />}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Preview />);
