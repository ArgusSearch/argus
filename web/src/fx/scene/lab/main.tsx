// The scene lab (web/fx-lab.html): the 3D metric graph full-window against the running API, with controls to
// restart the replay, switch theme and quality, play the intro again, teach the graph a metric (freeze-in) and
// read the frame budget. Dev only; Mission Control mounts the scene through the style layer instead.

import "./lab.css";
import { StrictMode, useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, follow, type ConnectionState } from "../../../lib/api";
import { emptyView, foldAll, recount, type RunView } from "../../../lib/store";
import type { Graph, ReplayStatus } from "../../../lib/types";
import GraphScene from "../GraphScene";
import type { SceneStats } from "../engine";

const LEARNED = "refund_rate";

/** The graph with one more metric, as a later graph version would bring it. */
function learn(graph: Graph): Graph {
  if (graph.nodes.some((n) => n.id === LEARNED)) return graph;
  const template = graph.nodes.find((n) => n.id === "orders") ?? graph.nodes[0];
  return {
    ...graph,
    version: graph.version + 1,
    nodes: [
      ...graph.nodes,
      { ...template, id: LEARNED, label: "Refund rate", description: "refunded orders per order (learned in the lab)", north_star: false, kind: "ratio", numerator: null, denominator: null },
    ],
    edges: [
      ...graph.edges,
      {
        id: `cause_${LEARNED}_gmv`,
        kind: "cause",
        target: "gmv",
        sources: [LEARNED],
        expr: null,
        dim: null,
        lag_hours: null,
        status: "PROBATION",
        weight: 1,
        provenance: "lab",
        last_test: null,
        note: "",
      },
    ],
  };
}

function setTheme(theme: "ice" | "night") {
  document.documentElement.dataset.fx = theme;
  window.dispatchEvent(new CustomEvent("fx:theme"));
}

function Lab() {
  const [base, setBase] = useState<Graph | null>(null);
  const [learned, setLearned] = useState(false);
  const [view, setView] = useState<RunView>(() => emptyView());
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [run, setRun] = useState<ReplayStatus | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [stats, setStats] = useState<SceneStats | null>(null);
  const [mountKey, setMountKey] = useState(0);
  const [preview, setPreview] = useState(new URLSearchParams(window.location.search).get("preview") === "1");
  const [theme, setThemeState] = useState<"ice" | "night">(document.documentElement.dataset.fx === "night" ? "night" : "ice");

  useEffect(() => {
    api.graph().then(setBase, () => undefined);
    api.health().then(
      (h) => setView((v) => ({ ...v, thresholds: h.thresholds, ...recount(v.zBuckets, h.thresholds) })),
      () => undefined,
    );
    return follow({
      onReset: (header) => setView((v) => emptyView(header.stream, header.mode, v.thresholds)),
      onEvents: (events) => setView((v) => foldAll(v, events)),
      onState: setConnection,
    });
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      setStats((window as unknown as { __fxScene?: SceneStats }).__fxScene ?? null);
      api.health().then(
        (h) => setRun(h.run),
        () => setRun(null),
      );
    }, 500);
    return () => clearInterval(timer);
  }, []);

  // the lab is its own style layer: it gives the intro cue as soon as the scene shows its first frame
  useEffect(() => {
    const cue = () => window.dispatchEvent(new CustomEvent("fx:intro", { detail: { duration: 3000 } }));
    window.addEventListener("fx:scene-ready", cue);
    return () => window.removeEventListener("fx:scene-ready", cue);
  }, []);

  const graph = useMemo(() => (base && learned ? learn(base) : base), [base, learned]);
  const control = useCallback((body: Parameters<typeof api.replay>[0]) => void api.replay(body).then(setRun, () => undefined), []);
  const quality = new URLSearchParams(window.location.search).get("fxq") ?? "auto";
  const qualityHref = (q: string) => {
    const params = new URLSearchParams(window.location.search);
    if (q === "auto") params.delete("fxq");
    else params.set("fxq", q);
    const s = params.toString();
    return s ? `?${s}` : window.location.pathname;
  };

  return (
    <>
      <div className="lab-stage">{graph && <GraphScene key={mountKey} graph={graph} view={view} onSelectNode={setSelected} />}</div>
      {preview && graph && (
        <div className="lab-preview" aria-label="affected path preview">
          <div className="lab-preview-title">// affected path</div>
          <div className="lab-preview-scene">
            <GraphScene graph={graph} view={view} onSelectNode={setSelected} variant="preview" />
          </div>
        </div>
      )}
      <aside className="lab-panel" aria-label="scene lab controls">
        <div className="lab-title">// argus scene lab</div>
        <div className="lab-row">
          <span className="lab-k">api</span>
          <span>
            {connection}
            {run && ` · ${run.position}/${run.total} · ${run.playing ? "playing" : "paused"} · ${run.speed}x`}
          </span>
        </div>
        <div className="lab-row">
          <button onClick={() => control({ action: "restart" })}>restart</button>
          <button onClick={() => control({ action: run?.playing ? "pause" : "play" })}>{run?.playing ? "pause" : "play"}</button>
          {[1, 2, 4].map((s) => (
            <button key={s} className={run?.speed === s ? "on" : ""} onClick={() => control({ speed: s })}>
              {s}x
            </button>
          ))}
        </div>
        <div className="lab-row">
          <span className="lab-k">theme</span>
          {(["ice", "night"] as const).map((t) => (
            <button
              key={t}
              className={theme === t ? "on" : ""}
              onClick={() => {
                setTheme(t);
                setThemeState(t);
              }}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="lab-row">
          <span className="lab-k">quality</span>
          {["auto", "high", "mid", "low"].map((q) => (
            <a key={q} className={quality === q ? "on" : ""} href={qualityHref(q)}>
              {q}
            </a>
          ))}
        </div>
        <div className="lab-row">
          <button onClick={() => setMountKey((k) => k + 1)}>replay intro</button>
          <button className={preview ? "on" : ""} onClick={() => setPreview((p) => !p)}>
            preview card
          </button>
          <button className={learned ? "on" : ""} onClick={() => setLearned((l) => !l)}>
            {learned ? "forget refund_rate" : "learn a metric"}
          </button>
        </div>
        <div className="lab-row">
          <span className="lab-k">clicked</span>
          <span className="lab-mono">{selected ?? "–"}</span>
        </div>
        <div className="lab-stats lab-mono">
          {stats
            ? `${stats.fps.toFixed(1)} fps · worst ${stats.worstMs.toFixed(1)} ms · cpu ${stats.cpuMs.toFixed(1)} ms\n${stats.calls} calls · ${stats.triangles} tris · ${stats.points} points\n${stats.width}x${stats.height} px · ratio ${stats.pixelRatio.toFixed(2)} · ${stats.tier}${stats.bloom ? "" : " · no bloom"}`
            : "measuring"}
        </div>
        <div className="lab-row lab-hint">phase {view.anomalies.length ? `${view.steps.length} steps` : "watching"} · {view.ticks} ticks</div>
      </aside>
    </>
  );
}

createRoot(document.getElementById("lab") as HTMLElement).render(
  <StrictMode>
    <Lab />
  </StrictMode>,
);
