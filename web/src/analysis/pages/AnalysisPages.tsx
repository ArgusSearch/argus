import { useState, type ReactNode } from "react";
import { Num, ReceiptChips, useOpenReceipt } from "../../components/Receipts";
import { dayLabel, eur, hhmm, humanize, pct, segmentLabel } from "../../lib/format";
import type { IncidentView, RunView } from "../../lib/store";
import type { Anomaly, Graph, GraphNode, Incident } from "../../lib/types";
import { health, keyMetrics } from "../../fx/workspace/health";
import { metricName, STATE, unusualness } from "../../fx/workspace/plain";
import { Card, Pill, useIncidents } from "../../fx/workspace/ui";
import { calendarEntries } from "../../settings/model";
import { metricStatus } from "../../views/model";
import { AnalyticsPanels, ShopMetrics, type AnalyticsPanelsProps } from "../analytics";
import { EvidenceCards } from "../cards/EvidenceCards";
import { analysisHref, followLink, navigateWorkspaceURL } from "../shell/location";
import { segmentKey, type AnalysisQuery } from "../shell/query";
import { AD_METRICS, FUNNEL_METRICS, inWindow, matchesSegment, observedSegments, visibleFindings, type AnalysisWindow } from "./model";

interface PageProps {
  graph: Graph | null;
  view: RunView;
  query: AnalysisQuery;
  window: AnalysisWindow;
  incidents: IncidentView[];
  signals: Anomaly[];
  navigate: (query: AnalysisQuery) => void;
  openIncident: (id: string) => void;
}

function QueryLink({ query, navigate, children }: Pick<PageProps, "query" | "navigate"> & { children: ReactNode }) {
  return <a href={analysisHref(query)} onClick={(event) => followLink(event, () => navigate(query))}>{children}</a>;
}

function incidentURL(id: string, receipt?: string) {
  const url = new URL(window.location.href);
  url.searchParams.set("view", "incident");
  url.searchParams.set("incident", id);
  if (receipt) url.searchParams.set("receipt", receipt);
  else url.searchParams.delete("receipt");
  return url.href;
}

function IncidentLink({ id, openIncident }: { id: string; openIncident: PageProps["openIncident"] }) {
  return <a href={incidentURL(id)} onClick={(event) => followLink(event, () => openIncident(id))}>{id}</a>;
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="fx-empty">{children}</p>;
}

function IncidentList({ graph, query, incidents, navigate, openIncident, window }: PageProps) {
  if (window.end === null) return <Empty>Waiting for run data.</Empty>;
  if (!incidents.length) return <Empty>No incidents match this query.</Empty>;
  return (
    <ul className="analysis-rows">
      {incidents.map((incident) => (
        <li key={incident.id} className="analysis-incident">
          <div>
            <strong>{incident.title}</strong>
            <span>{segmentLabel(incident.segment)}</span>
          </div>
          <div>
            <QueryLink query={{ ...query, page: "metrics", metric: incident.root_node, segment: incident.segment }} navigate={navigate}>
              {metricName(graph, incident.root_node)}
            </QueryLink>
            <QueryLink query={{ ...query, page: "segments", metric: incident.root_node, segment: incident.segment }} navigate={navigate}>
              View segment
            </QueryLink>
          </div>
          <Pill tone={STATE[incident.state].tone}>{STATE[incident.state].label}</Pill>
          <IncidentLink id={incident.id} openIncident={openIncident} />
        </li>
      ))}
    </ul>
  );
}

function Overview(props: PageProps) {
  const { graph, view, query, incidents, signals, window, navigate } = props;
  const openReceipt = useOpenReceipt();
  const status = health(view, graph);
  const ready = window.end !== null;
  const resolved = incidents.filter((incident) => incident.state === "resolved").length;
  const impact = incidents.reduce((sum, incident) => sum + Math.abs(incident.severity_eur), 0);
  const metricId = query.metric || "payment_success_rate";
  const scope = segmentKey(query.segment);
  const observations = signals.filter((signal) => signal.node === metricId && segmentKey(signal.segment) === scope);
  const stats = [
    ["Open incidents", ready ? incidents.length - resolved : null],
    ["Resolved incidents", ready ? resolved : null],
    ["Anomaly observations", ready ? signals.length : null],
    ["Measured incident impact", ready && incidents.length ? eur(impact) : null],
    ["Metrics in graph", graph?.nodes.length ?? null],
    ["Shop health", status.score === null ? null : `${status.score}/100`],
  ];
  return (
    <>
      <div className="analysis-stats">
        {stats.map(([label, value]) => (
          <dl key={label} className="ws-tile t-muted">
            <dt className="ws-tile-label">{label}</dt>
            <dd className="ws-tile-value"><b>{value ?? "—"}</b></dd>
          </dl>
        ))}
      </div>
      <ShopMetrics view={view} graph={graph} />
      <Card title="Affected metrics" action={<QueryLink query={{ ...query, page: "incidents" }} navigate={navigate}>All incidents</QueryLink>}>
        <IncidentList {...props} />
      </Card>
      {Object.keys(query.segment).length === 0 && <CurrentMetrics {...props} />}
      <EvidenceCards key={view.stream} view={view} graph={graph} metricId={metricId} observations={observations} statuses={incidents}
        renderReceipt={(id, label) => id && <button type="button" className="rcpt" onClick={() => openReceipt(id)}>{label}</button>} />
    </>
  );
}

function CurrentMetrics({ graph, view, query, navigate }: PageProps) {
  const ids = query.metric ? [query.metric] : keyMetrics(graph);
  const { alarm_z: alarm, wiggle_z: wiggle } = view.thresholds;
  return (
    <Card title="Latest metric checks">
      {graph && view.tick && ids.length ? (
        <table className="analysis-table">
          <thead><tr><th scope="col">Metric</th><th scope="col">Current status</th><th scope="col" className="analysis-number">Deviation (|z|)</th></tr></thead>
          <tbody>
            {ids.map((id) => {
              const state = metricStatus(view, id);
              const tone = state.state === "root" ? "alarm" : state.state === "checking" ? "probe" : unusualness(state.z, wiggle, alarm).tone;
              return (
                <tr key={id}>
                  <th scope="row"><QueryLink query={{ ...query, page: "metrics", metric: id }} navigate={navigate}>{metricName(graph, id)}</QueryLink></th>
                  <td><Pill tone={tone}>{state.label}</Pill></td>
                  <td className="analysis-number">{state.z?.toFixed(1) ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : <Empty>Waiting for scored metrics.</Empty>}
      {view.tick && <p className="fx-card-note">Whole-shop checks for {dayLabel(view.tick.hour)} {hhmm(view.tick.hour)} UTC.</p>}
    </Card>
  );
}

function observation(value: number, graph: Graph | null, signal: Anomaly) {
  const sourceUnit = graph?.nodes.find((node) => node.id === signal.node)?.unit;
  const unit = sourceUnit === "eur_per_unit" ? "eur" : sourceUnit ?? "value";
  const text = unit === "ratio" ? `${value.toLocaleString("en-US", { maximumFractionDigits: 3 })}×` : undefined;
  return <Num q={{ value, unit, receipt: signal.receipts[0] ?? null }} text={text} />;
}

function Signals({ graph, signals, window }: Pick<PageProps, "graph" | "signals" | "window">) {
  if (window.end === null) return <Empty>Waiting for run data.</Empty>;
  if (!signals.length) return <Empty>No anomaly observations match this query.</Empty>;
  return (
    <div className="analysis-table-scroll" tabIndex={0} role="region" aria-label="Anomaly observations table">
      <table className="analysis-table">
        <thead><tr><th scope="col">Metric and scope</th><th scope="col">Scored hour (UTC)</th><th scope="col" className="analysis-number">Observed</th><th scope="col" className="analysis-number">Expected range</th></tr></thead>
        <tbody>
          {signals.map((signal) => (
            <tr key={signal.id}>
              <th scope="row"><strong>{metricName(graph, signal.node)}</strong><span>{segmentLabel(signal.segment)}</span></th>
              <td>{dayLabel(signal.hour)} {hhmm(signal.hour)}</td>
              <td className="analysis-number">{observation(signal.observed, graph, signal)}</td>
              <td className="analysis-number">{observation(signal.band[0], graph, signal)} to {observation(signal.band[1], graph, signal)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type ScopedEvidenceProps = PageProps & { analytics?: AnalyticsPanelsProps["section"] };

function ScopedEvidence(props: ScopedEvidenceProps) {
  const [attempt, setAttempt] = useState(0);
  if (!props.analytics && !props.incidents.length) return null;
  return <EvidencePanels key={attempt} {...props} retry={() => setAttempt((count) => count + 1)} />;
}

function EvidencePanels({ analytics, retry, ...props }: ScopedEvidenceProps & { retry: () => void }) {
  const { graph, view, query, navigate } = props;
  const { incidents: details, failed } = useIncidents(view);
  return (
    <>
      {analytics && <AnalyticsPanels graph={graph} view={view} incidents={details} query={query} section={analytics}
        incidentError={failed && !props.incidents.length ? "Could not read incident findings." : null} onRetry={retry}
        onPeriodChange={(period) => navigate({ ...query, period })}
        segmentHref={(segment) => analysisHref({ ...query, page: "segments", segment })}
        incidentHref={incidentURL} onNavigate={(event) => followLink(event, () => navigateWorkspaceURL(event.currentTarget.href))} />}
      {props.incidents.length > 0 && <IncidentFindings {...props} details={details} failed={failed} retry={retry} />}
    </>
  );
}

function IncidentFindings({ graph, query, incidents, window, openIncident, details, failed, retry }: PageProps & {
  details: Incident[];
  failed: boolean;
  retry: () => void;
}) {
  const matching = new Map(incidents.map((incident) => [incident.id, incident]));
  const findings = details.filter((incident) => visibleFindings(incident, matching.get(incident.id), window)).flatMap(({ id, findings }) => {
    const root = findings.root;
    if (!root || (query.metric && root.node !== query.metric) || !matchesSegment(root.segment, query.segment)) return [];
    return [{ id, root }];
  });
  return (
    <Card title="Measured incident changes">
      {findings.length ? (
        <ul className="analysis-rows">
          {findings.map(({ id, root }) => {
            const receipt = root.change_pct.receipt;
            const href = receipt ? incidentURL(id, receipt) : null;
            return (
              <li key={id} className="analysis-incident">
                <div><strong>{metricName(graph, root.node)}</strong><span>{segmentLabel(root.segment)}</span></div>
                <span><strong>{pct(root.change_pct.value)}</strong> vs expected</span>
                {href && <a href={href} onClick={(event) => followLink(event, () => navigateWorkspaceURL(href))}>Receipt {receipt}</a>}
                <IncidentLink id={id} openIncident={openIncident} />
              </li>
            );
          })}
        </ul>
      ) : failed ? (
        <div>
          <Empty>Could not read incident findings.</Empty>
          <button className="btn" type="button" onClick={retry}>Retry</button>
        </div>
      ) : <Empty>No scoped finding is available at this point in the run.</Empty>}
    </Card>
  );
}

function MetricDefinitions({ graph, query, navigate, ids }: Pick<PageProps, "graph" | "query" | "navigate"> & { ids?: string[] }) {
  const nodes = ids
    ? ids.map((id) => graph?.nodes.find((node) => node.id === id)).filter((node): node is GraphNode => Boolean(node))
    : graph?.nodes ?? [];
  if (!graph) return <Empty>Waiting for the metric graph.</Empty>;
  const selected = nodes.find((node) => node.id === query.metric);
  if (selected && !ids) {
    const formula = selected.expr ?? (selected.numerator && selected.denominator
      ? `${metricName(graph, selected.numerator)} ÷ ${metricName(graph, selected.denominator)}`
      : null);
    return (
      <div className="analysis-definition">
        <strong>{selected.label}</strong>
        <p>{selected.description}</p>
        {formula && <code>{formula}</code>}
        {selected.dims.length > 0 && <small>Dimensions · {selected.dims.map(humanize).join(", ")}</small>}
      </div>
    );
  }
  if (!nodes.length) return <Empty>No matching metric definitions in this graph.</Empty>;
  return (
    <ul className="analysis-rows">
      {nodes.map((node) => (
        <li key={node.id}>
          <QueryLink query={{ ...query, page: "metrics", metric: node.id, segment: {} }} navigate={navigate}>{node.label}</QueryLink>
          <span>{node.description}</span>
        </li>
      ))}
    </ul>
  );
}

function SegmentList({ graph, view, query, navigate, window, signals, incidents }: PageProps) {
  if (!graph || window.end === null) return <Empty>Waiting for the metric graph and run data.</Empty>;
  const countries = query.page === "countries";
  const evidence = { ...view, anomalies: signals, incidents: Object.fromEntries(incidents.map((row) => [row.id, row])) };
  const scopes = observedSegments(evidence, graph, query.metric).filter((scope) => countries
    ? Object.keys(scope).length === 1 && Boolean(scope.country)
    : matchesSegment(scope, query.segment));
  if (!scopes.length) return <Empty>No {countries ? "countries" : "segments"} in the matching evidence.</Empty>;
  return (
    <ul className="analysis-rows">
      {scopes.map((scope) => (
        <li key={segmentKey(scope)}>
          <QueryLink query={{ ...query, page: "segments", segment: countries ? { ...query.segment, ...scope } : scope }} navigate={navigate}>
            {segmentLabel(scope)}
          </QueryLink>
          <span>{Object.keys(scope).map(humanize).join(", ")}</span>
        </li>
      ))}
    </ul>
  );
}

function Changes({ graph, view, query, window }: PageProps) {
  const anomalyIds = new Set(view.anomalies.filter((signal) => signal.node === query.metric).map((signal) => signal.id));
  const steps = view.steps.filter((step) => inWindow(step.simTs, { ...window, start: null }) && (!query.metric || anomalyIds.has(step.anomalyId)));
  const entries = calendarEntries({ ...view, steps }, graph).filter((entry) => {
    if (entry.lane !== "plan" || !inWindow(entry.ts, window)) return false;
    const scope = entry.plan?.scope;
    return Object.entries(query.segment).every(([dimension, value]) => !scope?.[dimension]?.length || scope[dimension].includes(value));
  });
  return !entries.length ? <Empty>{window.end === null ? "Waiting for run data." : "No investigation change records match this query."}</Empty> : (
    <ul className="analysis-rows">
      {entries.map((entry) => (
        <li key={entry.id}>
          <strong>{entry.title}</strong>
          <span>{dayLabel(entry.ts)} {hhmm(entry.ts)} UTC · {entry.detail}</span>
          <ReceiptChips ids={entry.receipts} />
        </li>
      ))}
    </ul>
  );
}

export function AnalysisPages(props: PageProps) {
  switch (props.query.page) {
    case "overview":
      return <Overview {...props} />;
    case "metrics":
      return props.query.metric ? (
        <>
          <div className="analysis-columns">
            <Card title="Metric definition"><MetricDefinitions {...props} /></Card>
            <Card title="Related incidents"><IncidentList {...props} /></Card>
          </div>
          <ScopedEvidence key={props.view.stream} {...props} analytics="both" />
          <Card title="Anomaly observations"><Signals {...props} /></Card>
        </>
      ) : (
        <>
          <Card title="Affected metrics"><IncidentList {...props} /></Card>
          <Card title="Metric definitions"><MetricDefinitions {...props} /></Card>
        </>
      );
    case "segments":
    case "countries":
      return (
        <>
          <Card title={props.query.page === "countries" ? "Countries in matching evidence" : "Segments in matching evidence"}><SegmentList {...props} /></Card>
          <Card title="Related incidents"><IncidentList {...props} /></Card>
          <ScopedEvidence key={props.view.stream} {...props} analytics={props.query.page === "countries" ? "distribution" : undefined} />
          <Card title="Anomaly observations"><Signals {...props} /></Card>
        </>
      );
    case "ads":
    case "funnel": {
      const ads = props.query.page === "ads";
      const ids = ads ? AD_METRICS : FUNNEL_METRICS;
      return (
        <>
          <Card title="Related incidents"><IncidentList {...props} incidents={props.incidents.filter((incident) => ids.includes(incident.root_node))} /></Card>
          <Card title={ads ? "Advertising metric definitions" : "Funnel steps"}><MetricDefinitions {...props} ids={ids} /></Card>
        </>
      );
    }
    case "incidents":
      return <Card title="Incidents in this period"><IncidentList {...props} /></Card>;
    case "changes":
      return <Card title="Changes checked in investigations"><Changes {...props} /></Card>;
    case "live-fix":
      return null;
  }
}
