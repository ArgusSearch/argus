import { ReactFlowProvider } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Feed } from "./components/Feed";
import { Header } from "./components/Header";
import { IncidentSheet } from "./components/IncidentSheet";
import { NodeSheet } from "./components/NodeSheet";
import { AutonomyLegend, DigestModal } from "./components/Overlays";
import { ReceiptProvider } from "./components/Receipts";
import { Ticker } from "./components/Ticker";
import { Trail } from "./components/Trail";
import { FxWorkspace, fxOn, GraphStage, openIncidentPage, useStoryFocus } from "./fx";
import { go } from "./fx/nav";
import { GraphExtensionLayer, useGraphExtension } from "./graph-extension";
import { demoGraph, useAgentDemo } from "./lib/agentDemo";
import { pollEvents } from "./lib/deployment";
import { api, follow, type ConnectionState } from "./lib/api";
import { checkingNode, emptyView, foldAll, recount, type RunView } from "./lib/store";
import type { Graph, Health } from "./lib/types";
import { OfflineBanner, Skeleton } from "./ui";
import { ViewHost } from "./views";

/** The graph's legend in plain words: what a line is, and what a block's color says. */
function Legend() {
  const line = (dash: string | undefined, color: string) => (
    <svg width="26" height="8" aria-hidden>
      <line x1="1" x2="25" y1="4" y2="4" stroke={color} strokeWidth="1.8" strokeDasharray={dash} />
    </svg>
  );
  return (
    <div className="legend">
      <span className="legend-item">{line(undefined, "#6b7590")}built from</span>
      <span className="legend-item">{line("2 4", "#7a76b8")}change log</span>
      <span className="legend-item">
        <span className="swatch" style={{ borderColor: "#3fbf8f" }} />
        normal
      </span>
      <span className="legend-item">
        <span className="swatch" style={{ borderColor: "#e3a63b" }} />
        unusual
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

function linkedIncident(): string | null {
  return fxOn() ? null : new URLSearchParams(window.location.search).get("incident");
}

function rememberIncident(id: string | null) {
  if (document.documentElement.classList.contains("argus-demo")) return;
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("incident", id);
  else {
    url.searchParams.delete("incident");
    if (url.searchParams.get("view") === "incident") url.searchParams.delete("view");
  }
  if (url.href !== window.location.href) window.history.pushState(null, "", url);
}

export function App() {
  const [baseGraph, setGraph] = useState<Graph | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [presentationGraph, setPresentationGraph] = useState<{ runId: string; graph?: Graph; error?: string } | null>(null);
  const [view, setView] = useState<RunView>(() => emptyView());
  const [health, setHealth] = useState<Health | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [incidentId, setIncidentId] = useState(linkedIncident);
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [digestOpen, setDigestOpen] = useState(false);
  const [toast, setToast] = useState<{ text: string; incident?: string; digest?: boolean } | null>(null);
  const announced = useRef(new Set<string>());
  const demo = useAgentDemo();
  const demoRun = demo?.runId;
  const scopedGraph = presentationGraph?.runId === demoRun ? presentationGraph : null;
  const graph = demoRun ? scopedGraph?.graph ?? null : baseGraph;
  const mapError = demoRun ? scopedGraph?.error : graphError;
  // a new metric placed itself (POST /graph/metrics): refetch the graph so the node appears everywhere
  const loadGraph = useCallback(() => {
    void api.graph().then(
      (next) => {
        setGraph(next);
        setGraphError(null);
      },
      (error: Error) => setGraphError(error.message),
    );
  }, []);
  const extension = useGraphExtension(loadGraph);

  useEffect(() => {
    if (!demoRun) return;
    let active = true;
    void demoGraph(demoRun).then(
      (graph) => active && setPresentationGraph({ runId: demoRun, graph }),
      (error: Error) => active && setPresentationGraph({ runId: demoRun, error: error.message }),
    );
    return () => {
      active = false;
    };
  }, [demoRun]);

  useEffect(() => {
    loadGraph();
    return follow({
      onReset: (header) => {
        setView((v) => emptyView(header.stream, header.mode, v.thresholds));
        announced.current = new Set();
        setToast(null);
        // Fresh connections send a stream header, including when the API comes back online.
        loadGraph();
      },
      onEvents: (events) => setView((v) => foldAll(v, events)),
      onState: setConnection,
    });
  }, [loadGraph]);

  // the watcher's lines come from the API; counters folded before they arrived are recounted
  const thresholds = health?.thresholds;
  useEffect(() => {
    if (!thresholds) return;
    setView((v) =>
      v.thresholds.alarm_z === thresholds.alarm_z && v.thresholds.wiggle_z === thresholds.wiggle_z
        ? v
        : { ...v, thresholds, ...recount(v.zBuckets, thresholds) },
    );
  }, [thresholds]);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) await api.health().then(
        (h) => live && setHealth(h),
        () => live && setHealth(null),
      );
      if (live) timer = setTimeout(poll, pollEvents ? 4000 : 1000);
    };
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, []);

  // announce verdicts and the end of the run once per stream
  useEffect(() => {
    if (demoRun) {
      setToast(null);
      return;
    }
    for (const inc of Object.values(view.incidents)) {
      const key = `${inc.id}:explained`;
      if (inc.verdict !== "UNEXPLAINED" && !announced.current.has(key)) {
        announced.current.add(key);
        setToast({ text: `${inc.id} explained: ${inc.title}`, incident: inc.id });
      }
    }
    if (health?.run.finished && view.lastSeq >= health.last_seq && !announced.current.has("end")) {
      announced.current.add("end");
      setToast({ text: "Run complete. Argus handled it alone.", digest: true });
    }
  }, [demoRun, view.incidents, view.lastSeq, health?.run.finished, health?.last_seq]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 9000);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (fxOn()) return;
    const restore = () => setIncidentId(linkedIncident());
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  const closeIncident = useCallback(() => {
    setIncidentId(null);
    rememberIncident(null);
  }, []);
  // with the style layer an incident opens as its own page; without it, as the sheet over the graph
  const openIncident = useCallback((id: string) => {
    if (fxOn()) openIncidentPage(id);
    else {
      setIncidentId(id);
      rememberIncident(id);
    }
    setToast(null);
  }, []);
  const closeDigest = useCallback(() => setDigestOpen(false), []);
  const openDigest = useCallback(() => {
    if (fxOn()) go("report");
    else setDigestOpen(true);
    setToast(null);
  }, []);
  const closeNode = useCallback(() => setNodeId(null), []);
  // during the agent presentation (lane F) the page shows the presentation's snapshot, not the live stream
  const shown = useMemo(
    () => (demo?.snapshot ? foldAll(emptyView(`demo:${demo.runId}`, "replay", view.thresholds), demo.snapshot.events) : view),
    [demo?.runId, demo?.snapshot, view],
  );
  const checking = checkingNode(shown);
  // the visualization's incident story lights its path on the map (style layer only; null otherwise)
  const story = useStoryFocus();
  const sceneView = useMemo(() => (story ? { ...shown, focus: story } : shown), [shown, story]);

  return (
    <ReceiptProvider rerunAvailable={health?.rerun === true}>
      <div className="app">
        <Header
          view={shown}
          health={health}
          connection={connection}
          onDigest={openDigest}
          presenting={demo !== null}
        />
        <Ticker view={shown} />
        <ViewHost graph={graph} view={shown} health={health} onSelectNode={setNodeId} onOpenIncident={openIncident}>
        <div className="main">
          <div className="left">
            <section className="graph" aria-label="metric graph">
              <div className="graph-bar">
                <span className="panel-title">How your shop's numbers connect</span>
                <span className="sub">Argus follows these lines to find the cause.</span>
                {checking && (
                  <span className="checking">
                    checking <b className="mono">{checking}</b>
                  </span>
                )}
              </div>
              <div className="graph-canvas">
                <OfflineBanner connection={connection} />
                {connection !== "offline" && mapError && <div className="banner" role="alert">Metric map could not be loaded. {mapError}</div>}
                {connection !== "offline" && !mapError && !graph && <Skeleton variant="graph" label="Loading the metric map" />}
                {graph && (
                  <ReactFlowProvider>
                    <GraphStage graph={graph} view={sceneView} onSelectNode={setNodeId} />
                  </ReactFlowProvider>
                )}
                {!demoRun && <GraphExtensionLayer ext={extension} />}
              </div>
              <div className="graph-foot">
                <Legend />
                {graph && <AutonomyLegend view={shown} graph={graph} />}
              </div>
            </section>
            <Trail view={shown} />
          </div>
          <Feed view={shown} graph={graph} onOpenIncident={openIncident} />
        </div>
        </ViewHost>
        <FxWorkspace graph={graph} view={shown} onOpenIncident={openIncident} onSelectNode={setNodeId} />
      </div>
      {incidentId && (
        <IncidentSheet key={incidentId} id={incidentId} summary={shown.incidents[incidentId]} graph={graph} onClose={closeIncident} />
      )}
      {nodeId && graph && <NodeSheet id={nodeId} graph={graph} view={shown} onClose={closeNode} />}
      {digestOpen && <DigestModal version={view.lastSeq} onClose={closeDigest} />}
      {toast && (
        <div className="toast" role="status">
          <span>{toast.text}</span>
          {toast.incident && (
            <button
              className="btn primary"
              onClick={() => toast.incident && openIncident(toast.incident)}
            >
              Open report
            </button>
          )}
          {toast.digest && (
            <button
              className="btn primary"
              onClick={openDigest}
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
