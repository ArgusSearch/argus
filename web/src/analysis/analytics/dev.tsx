import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/ibm-plex-mono/400.css";
import "../../styles.css";
import "../../fx/tokens.css";
import "../../fx/base.css";
import "../../fx/fx.css";
import "../../fx/workspace/workspace.css";
import { ReceiptProvider } from "../../components/Receipts";
import { wherePhrase } from "../../fx/workspace/plain";
import { api, follow, json, type ConnectionState } from "../../lib/api";
import { emptyView, foldAll } from "../../lib/store";
import type { Graph, Incident, Segment } from "../../lib/types";
import { AnalyticsPanels, ShopMetrics, type AnalyticsPeriod } from "./index";
import { HISTORY_PERIODS, dateTime, time } from "./model";
import "./dev.css";

interface RunDetails {
  key: string;
  incidents: Incident[];
  error: string | null;
}

const INITIAL_QUERY = new URLSearchParams(location.search);
const periodParam = INITIAL_QUERY.get("period");
const defaultPeriod = HISTORY_PERIODS.find(([period]) => period === periodParam)?.[0] ?? "30d";

function Dev() {
  const [view, setView] = useState(() => emptyView());
  const [graph, setGraph] = useState<Graph | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [graphError, setGraphError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [details, setDetails] = useState<RunDetails>();
  const [period, setPeriod] = useState<AnalyticsPeriod>(defaultPeriod);
  const [metric, setMetric] = useState(INITIAL_QUERY.get("metric") ?? "payment_success_rate");
  const [selected, setSelected] = useState(INITIAL_QUERY.get("segment") ?? "");
  const incidentID = INITIAL_QUERY.get("incident") ?? undefined;
  const version = Object.values(view.incidents).map(({ id, lastSeq }) => `${id}:${lastSeq}`).join(",");
  const runKey = `${view.stream}/${version}`;
  const retry = () => setAttempt((value) => value + 1);

  useEffect(() => follow({
    onReset: (header) => setView(emptyView(header.stream, header.mode)),
    onEvents: (events) => setView((previous) => foldAll(previous, events)),
    onState: setConnection,
  }), []);

  useEffect(() => {
    let active = true;
    api.graph().then(
      (result) => { if (active) { setGraph(result); setGraphError(false); } },
      () => { if (active) setGraphError(true); },
    );
    return () => { active = false; };
  }, [view.stream, attempt]);

  useEffect(() => {
    if (!view.stream || !version) return;
    const signal = new AbortController();
    json<Incident[]>("/incidents", { signal: AbortSignal.any([signal.signal, AbortSignal.timeout(12_000)]) }).then(
      (incidents) => { if (!signal.signal.aborted) setDetails({ key: runKey, incidents, error: null }); },
      () => { if (!signal.signal.aborted) setDetails({ key: runKey, incidents: [], error: "Incident evidence could not be loaded." }); },
    );
    return () => signal.abort();
  }, [view.stream, version, runKey, attempt]);

  const scopes = useMemo(() => {
    const result = new Map<string, Segment>();
    for (const incident of Object.values(view.incidents)) {
      if (incident.root_node !== metric) continue;
      const entries = Object.entries(incident.segment);
      for (let depth = 1; depth <= entries.length; depth++) {
        const segment = Object.fromEntries(entries.slice(0, depth));
        result.set(JSON.stringify(segment), segment);
      }
    }
    return result;
  }, [view.incidents, metric]);

  const at = time(view.simTs);
  const incidents = details?.key === runKey ? details.incidents : [];
  const error = details?.key === runKey ? details.error : null;
  const segment = scopes.get(selected) ?? {};
  const query = { metric, segment, period };
  const scopedURL = (next: Segment) => {
    const url = new URL(location.href);
    url.searchParams.set("metric", metric);
    url.searchParams.set("period", period);
    url.searchParams.set("segment", JSON.stringify(next));
    return url.href;
  };
  const incidentHref = (id: string) => `/?view=incident&incident=${encodeURIComponent(id)}`;

  return (
    <ReceiptProvider rerunAvailable={false}>
      <main className="an-dev">
        <header className="an-dev-head">
          <div>
            <h1>Analytics</h1>
            <p>{view.mode === "replay" ? "Replay" : view.mode === "live" ? "Live" : "Connecting to Argus"}{at !== null && ` · As of ${dateTime(at)}`}</p>
          </div>
          <div className="an-dev-query">
            <label>
              Metric
              <select name="metric" value={metric} onChange={(event) => { setMetric(event.target.value); setSelected(""); }}>
                {!graph && <option value={metric}>Loading metrics…</option>}
                {graph?.nodes.map(({ id, label }) => <option value={id} key={id}>{label}</option>)}
              </select>
            </label>
            <label>
              Scope
              <select name="segment" value={scopes.has(selected) ? selected : ""} onChange={(event) => setSelected(event.target.value)}>
                <option value="">Whole shop</option>
                {[...scopes].map(([key, value]) => <option value={key} key={key}>{wherePhrase(value)}</option>)}
              </select>
            </label>
          </div>
        </header>
        {connection === "offline" && <p className="an-state" role="status">Argus is offline. Showing the last received evidence.</p>}
        {graphError && <p className="an-state" role="status">The metric graph could not be loaded. <button type="button" onClick={retry}>Retry</button></p>}
        <ShopMetrics graph={graph} view={view} />
        <AnalyticsPanels graph={graph} view={view} incidents={incidents} query={query} incidentId={incidentID}
          segmentHref={scopedURL} incidentHref={incidentHref} incidentError={error} onRetry={retry} onPeriodChange={setPeriod} />
      </main>
    </ReceiptProvider>
  );
}

createRoot(document.getElementById("root")!).render(<Dev />);
