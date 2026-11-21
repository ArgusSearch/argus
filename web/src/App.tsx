import { ReactFlowProvider } from "@xyflow/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Feed } from "./components/Feed";
import { GraphView } from "./components/GraphView";
import { Header } from "./components/Header";
import { IncidentSheet } from "./components/IncidentSheet";
import { NodeSheet } from "./components/NodeSheet";
import { AutonomyLegend, DigestModal } from "./components/Overlays";
import { ReceiptProvider } from "./components/Receipts";
import { Ticker } from "./components/Ticker";
import { Trail } from "./components/Trail";
import { api, follow, type ConnectionState } from "./lib/api";
import { emptyView, foldAll, type RunView } from "./lib/store";
import type { Graph, Health } from "./lib/types";

function Legend() {
  const line = (dash: string | undefined, color: string) => (
    <svg width="26" height="8" aria-hidden>
      <line x1="1" x2="25" y1="4" y2="4" stroke={color} strokeWidth="1.8" strokeDasharray={dash} />
    </svg>
  );
  return (
    <div className="legend">
      <span className="legend-item">{line(undefined, "#6b7590")}formula</span>
      <span className="legend-item">{line("2 4", "#7a76b8")}evidence</span>
      <span className="legend-item">{line("6 5", "#e3a63b")}cause (probation)</span>
      <span className="legend-item">{line(undefined, "#f2585d")}broken</span>
      <span className="legend-item">
        <span className="swatch" style={{ borderColor: "#e3a63b" }} />
        wiggle
      </span>
      <span className="legend-item">
        <span className="swatch" style={{ borderColor: "#f2585d" }} />
        alarm
      </span>
      <span className="legend-item">
        <span className="swatch" style={{ borderColor: "#5aa7ff" }} />
        being checked
      </span>
    </div>
  );
}

export function App() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [view, setView] = useState<RunView>(() => emptyView());
  const [health, setHealth] = useState<Health | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [digestOpen, setDigestOpen] = useState(false);
  const [toast, setToast] = useState<{ text: string; incident?: string; digest?: boolean } | null>(null);
  const announced = useRef(new Set<string>());

  useEffect(
    () =>
      follow({
        onReset: (header) => {
          setView(emptyView(header.stream, header.mode));
          announced.current = new Set();
          setToast(null);
          api.graph().then(setGraph, () => undefined);
        },
        onEvents: (events) => setView((v) => foldAll(v, events)),
        onState: setConnection,
      }),
    [],
  );

  useEffect(() => {
    let live = true;
    const poll = () =>
      api.health().then(
        (h) => live && setHealth(h),
        () => live && setHealth(null),
      );
    poll();
    const timer = setInterval(poll, 1000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  // announce verdicts and the end of the run once per stream
  useEffect(() => {
    for (const inc of Object.values(view.incidents)) {
      const key = `${inc.id}:explained`;
      if (inc.verdict !== "UNEXPLAINED" && !announced.current.has(key)) {
        announced.current.add(key);
        setToast({ text: `${inc.id} explained: ${inc.title}`, incident: inc.id });
      }
    }
    if (health?.replay?.finished && view.lastSeq >= (health.replay.total || Infinity) && !announced.current.has("end")) {
      announced.current.add("end");
      setToast({ text: "Run complete. Argus handled it alone.", digest: true });
    }
  }, [view.incidents, view.lastSeq, health?.replay?.finished, health?.replay?.total]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 9000);
    return () => clearTimeout(timer);
  }, [toast]);

  const closeIncident = useCallback(() => setIncidentId(null), []);
  const openIncident = useCallback((id: string) => {
    setIncidentId(id);
    setToast(null);
  }, []);
  const closeDigest = useCallback(() => setDigestOpen(false), []);
  const closeNode = useCallback(() => setNodeId(null), []);
  const latest = view.anomalies[view.anomalies.length - 1];

  return (
    <ReceiptProvider>
      <div className="app">
        <Header view={view} health={health} connection={connection} onDigest={() => setDigestOpen(true)} />
        <Ticker view={view} />
        <div className="main">
          <div className="left">
            <section className="graph" aria-label="metric graph">
              <div className="graph-bar">
                <span className="panel-title">Metric graph</span>
                <span className="sub">
                  {graph ? `${graph.nodes.length} metrics · ${graph.edges.length} typed edges, each with a live test · ${graph.logs.length} logs` : "loading"}
                </span>
                {latest && view.focus && (
                  <span className="checking">
                    checking <b className="mono">{latest.node}</b>
                  </span>
                )}
              </div>
              <div className="graph-canvas">
                {connection === "offline" && <div className="banner">The API is offline. Start it with make api.</div>}
                {graph && (
                  <ReactFlowProvider>
                    <GraphView graph={graph} view={view} onSelectNode={setNodeId} />
                  </ReactFlowProvider>
                )}
              </div>
              <div className="graph-foot">
                <Legend />
                {graph && <AutonomyLegend view={view} graph={graph} />}
              </div>
            </section>
            <Trail view={view} />
          </div>
          <Feed view={view} onOpenIncident={openIncident} />
        </div>
      </div>
      {incidentId && <IncidentSheet id={incidentId} summary={view.incidents[incidentId]} onClose={closeIncident} />}
      {nodeId && graph && <NodeSheet id={nodeId} graph={graph} view={view} onClose={closeNode} />}
      {digestOpen && <DigestModal version={view.lastSeq} onClose={closeDigest} />}
      {toast && (
        <div className="toast" role="status">
          <span>{toast.text}</span>
          {toast.incident && (
            <button
              className="btn primary"
              onClick={() => {
                setIncidentId(toast.incident ?? null);
                setToast(null);
              }}
            >
              Open report
            </button>
          )}
          {toast.digest && (
            <button
              className="btn primary"
              onClick={() => {
                setDigestOpen(true);
                setToast(null);
              }}
            >
              While you slept
            </button>
          )}
          <button className="icon-btn" onClick={() => setToast(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
    </ReceiptProvider>
  );
}
