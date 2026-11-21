// The metric graph: typed edges with their live test status, node states, attention heat and the
// investigation walk (the edges and nodes the current trail step touches light up).

import { Handle, MarkerType, Position, ReactFlow, useReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { verdictLabel } from "../lib/format";
import { freshAnomaly, isRuledOut, type Focus, type RunView } from "../lib/store";
import type { EdgeStatus, EvidenceRef, Graph, GraphEdge, GraphNode } from "../lib/types";
import { Sparkline } from "./charts";

// The north-star metrics carry the graph at full size; the other metrics and the logs are compact.
const NODE_W = 160;
const NODE_H = 46;
const SMALL_W = 124;
const SMALL_H = 30;
const LOG_W = 136;
const LOG_H = 30;

type Tone = "normal" | "wiggle" | "alarm" | "symptom" | "root" | "resolved";

interface MetricData extends Record<string, unknown> {
  node: GraphNode;
  z: number;
  history: number[];
  heat: number;
  tone: Tone;
  focus: boolean;
  tag: string | null;
  alarm: number;
  scored: boolean;
  /** on the affected path of the open incident */
  path: boolean;
  /** an incident path is on screen and this node is not on it */
  recede: boolean;
}

interface LogData extends Record<string, unknown> {
  id: string;
  label: string;
  focus: boolean;
  path: boolean;
  recede: boolean;
}

const PATH_COLOR = "#ff7a5c";

const SHORT_LABEL: Record<string, string> = {
  payment_success_rate: "Payment success",
  impressions_per_session: "Impr. per session",
  aov: "Order value (AOV)",
  cvr: "Conversion",
  payment_attempts: "Pay attempts",
  payment_successes: "Pay successes",
};

const MetricNode = memo(function MetricNode({ data }: NodeProps<Node<MetricData>>) {
  const { node, z, history, heat, tone, focus, tag, alarm, scored, path, recede } = data;
  const glow =
    path && !focus && tone !== "root" && tone !== "alarm"
      ? `0 0 18px rgba(255, 122, 92, 0.35)`
      : heat > 0.05 && !focus
        ? `0 0 ${10 + 26 * heat}px rgba(227, 166, 59, ${0.12 + 0.4 * heat})`
        : undefined;
  const sparkTone = tone === "alarm" || tone === "root" ? "alarm" : tone === "wiggle" ? "watch" : "muted";
  const className = `mnode ${tone}${focus ? " focus" : ""}${scored ? "" : " unscored"}`;
  const title = `${node.label}: ${node.description}${scored ? "" : " (scored when an investigation needs it)"}`;
  const style = {
    boxShadow: glow,
    opacity: recede && !focus ? 0.32 : 1,
    borderColor: path && tone !== "root" && tone !== "alarm" && !focus ? PATH_COLOR : undefined,
  };
  if (!node.north_star) {
    // compact: name and |z| on one line; the full card is for the metrics the watcher scores every hour
    return (
      <div className={className} style={{ ...style, width: SMALL_W, height: SMALL_H, padding: "6px 9px" }} title={title}>
        <Handle type="target" position={Position.Left} />
        <Handle type="source" position={Position.Right} />
        {tag && <span className="mnode-tag">{tag}</span>}
        <div className="mnode-head">
          <span className="mnode-label" style={{ fontSize: 11, fontWeight: 500 }}>
            {SHORT_LABEL[node.id] ?? node.label}
          </span>
          {Number.isFinite(z) && <span className="mnode-z">{z.toFixed(1)}</span>}
        </div>
      </div>
    );
  }
  return (
    <div className={className} style={{ ...style, width: NODE_W }} title={title}>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      {tag && <span className="mnode-tag">{tag}</span>}
      <div className="mnode-head">
        {node.north_star && <span className="mnode-star" aria-label="north star">★</span>}
        <span className="mnode-label" style={{ fontSize: 13.5, fontWeight: 650 }}>
          {SHORT_LABEL[node.id] ?? node.label}
        </span>
      </div>
      <div className="mnode-foot">
        <span className="mnode-kind">{node.kind === "ratio" ? "rate" : node.unit}</span>
        <Sparkline values={history} width={54} height={12} max={Math.max(alarm + 1, ...history)} tone={sparkTone} />
        <span className="mnode-z">{Number.isFinite(z) ? z.toFixed(1) : "–"}</span>
      </div>
    </div>
  );
});

const LogNode = memo(function LogNode({ data }: NodeProps<Node<LogData>>) {
  return (
    <div
      className={`lnode${data.focus ? " focus" : ""}`}
      style={{
        width: LOG_W,
        height: LOG_H,
        padding: "3px 10px",
        fontSize: 11,
        opacity: data.recede && !data.focus ? 0.32 : 1,
        borderColor: data.path && !data.focus ? PATH_COLOR : undefined,
        borderStyle: data.path ? "solid" : undefined,
      }}
      title="log of state changes (evidence source)"
    >
      <Handle type="source" position={Position.Right} />
      {data.label}
      <span className="mono">{data.id}</span>
    </div>
  );
});

const nodeTypes = { metric: MetricNode, log: LogNode };

interface Link {
  id: string;
  edge: GraphEdge | null; // null: a ratio's definition (numerator / denominator)
  source: string;
  target: string;
}

function links(graph: Graph): Link[] {
  const out: Link[] = [];
  for (const e of graph.edges) {
    if (e.kind === "breakdown") continue; // a split of the node itself, shown on the node
    for (const s of e.sources) out.push({ id: `${e.id}:${s}`, edge: e, source: s, target: e.target });
  }
  // A ratio's numerator and denominator, drawn faintly, unless the ratio is itself a factor of a formula
  // (ctr in clicks = impressions x ctr): then the formula already says how they relate.
  const factors = new Set(graph.edges.filter((e) => e.kind === "formula").flatMap((e) => e.sources));
  for (const n of graph.nodes) {
    if (n.kind !== "ratio" || factors.has(n.id)) continue;
    for (const part of [n.numerator, n.denominator]) {
      if (part) out.push({ id: `def:${n.id}:${part}`, edge: null, source: part, target: n.id });
    }
  }
  return out;
}

// Inputs on the left, outcomes on the right; the shop above, the ads business below.
// [column, row]; metrics the graph learns later get a column of their own.
const GRID: Record<string, [number, number]> = {
  log_calendar: [0, 0],
  log_deploys: [0, 3.2],
  log_provider_status: [0, 6],
  sessions: [1, 0],
  product_views: [1, 1],
  carts: [1, 2],
  checkouts: [1, 3],
  payment_attempts: [1, 4],
  payment_successes: [1, 5],
  view_rate: [2, 1],
  cart_rate: [2, 2],
  checkout_rate: [2, 3],
  attempt_rate: [2, 4],
  payment_success_rate: [2, 5],
  cvr: [3, 3],
  orders: [4, 2],
  aov: [4, 4],
  gmv: [5, 3],
  impressions_per_session: [2, 7],
  ad_impressions: [3, 7],
  ctr: [3, 8],
  ad_clicks: [4, 7.5],
  cpc: [4, 8.5],
  ad_spend: [5, 8],
  attributed_gmv: [5, 6.6],
  log_ad_budgets: [4, 9.8],
  planned_spend: [5, 9.3],
  ad_conversions: [5, 10.3],
  roas: [6, 6.9],
  pacing_ratio: [6, 8.6],
  cpa: [6, 9.8],
};
const ROW_H = 50;
const MIN_COL_W = 174;
const MAX_COL_W = 300;

/**
 * Positions on the grid. The columns widen with a wide panel (`aspect` is its width over its height), so the
 * graph fills the panel instead of sitting small in its middle.
 */
function layout(graph: Graph, aspect: number): Record<string, { x: number; y: number }> {
  const pos: Record<string, { x: number; y: number }> = {};
  const extraCol = Math.max(...Object.values(GRID).map(([c]) => c)) + 1;
  const cols = Math.max(...graph.nodes.map((n) => GRID[n.id]?.[0] ?? extraCol), ...graph.logs.map((l) => GRID[l.id]?.[0] ?? extraCol), 1);
  const height = Math.max(...Object.values(GRID).map(([, r]) => r)) * ROW_H + NODE_H;
  const colW = Math.min(MAX_COL_W, Math.max(MIN_COL_W, (aspect * height - NODE_W) / cols));
  let extraRow = 0;
  const place = (id: string, w: number, h: number) => {
    const cell = GRID[id] ?? [extraCol, extraRow++];
    pos[id] = { x: cell[0] * colW + (NODE_W - w) / 2, y: cell[1] * ROW_H + (NODE_H - h) / 2 };
  };
  for (const n of graph.nodes) place(n.id, n.north_star ? NODE_W : SMALL_W, n.north_star ? NODE_H : SMALL_H);
  for (const l of graph.logs) place(l.id, LOG_W, LOG_H);
  return pos;
}

/**
 * The affected path of the open investigation: the anomalous metric, everything its formulas move downstream,
 * and the logs whose evidence held. Empty when there is no anomaly or its incident is resolved.
 */
function affectedPath(graph: Graph, view: RunView): Set<string> {
  const out = new Set<string>();
  const anomaly = view.anomalies[view.anomalies.length - 1];
  if (!anomaly) return out;
  if (Object.values(view.incidents).some((inc) => inc.root_node === anomaly.node && inc.state === "resolved")) return out;
  out.add(anomaly.node);
  for (let grew = true; grew; ) {
    grew = false;
    for (const e of graph.edges) {
      if (e.kind === "formula" && !out.has(e.target) && e.sources.some((s) => out.has(s))) {
        out.add(e.target);
        grew = true;
      }
    }
  }
  for (const s of view.steps) {
    const event = s.step.data?.event as EvidenceRef | undefined;
    if (s.anomalyId === anomaly.id && s.step.kind === "holdout" && event?.log && !isRuledOut(s.step.decision)) out.add(event.log);
  }
  return out;
}

const STATUS_COLOR: Record<EdgeStatus, string> = {
  VALID: "#4a5568",
  SUPPORTED: "#5b5a8a",
  PROBATION: "#e3a63b",
  PROPOSED: "#3a4256",
  BROKEN: "#f2585d",
};

function linkStyle(link: Link, status: EdgeStatus | null, focused: boolean, onPath = false): Partial<Edge> {
  if (onPath && !focused) {
    return {
      animated: true,
      style: { stroke: PATH_COLOR, strokeWidth: 2.4 },
      markerEnd: { type: MarkerType.ArrowClosed, color: PATH_COLOR, width: 16, height: 16 },
      zIndex: 9,
    };
  }
  if (focused) {
    return {
      animated: true,
      style: { stroke: "#5aa7ff", strokeWidth: 2.2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#5aa7ff", width: 16, height: 16 },
      zIndex: 10,
    };
  }
  if (!link.edge) return { style: { stroke: "#232b3b", strokeWidth: 1, strokeDasharray: "2 4" } };
  const color = STATUS_COLOR[status ?? link.edge.status];
  const dash =
    link.edge.kind === "cause" ? "6 5" : link.edge.kind === "evidence" ? "2 4" : status === "PROPOSED" ? "2 5" : undefined;
  return {
    style: { stroke: color, strokeWidth: link.edge.kind === "formula" ? 1.6 : 1.2, strokeDasharray: dash },
    markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
  };
}

function focusSets(focus: Focus | null) {
  const nodes = new Set(focus?.nodes ?? []);
  const logs = new Set(focus?.logs ?? []);
  const edges = new Set<string>();
  for (const e of focus?.edges ?? []) {
    if (e.startsWith("b_")) continue;
    edges.add(e);
  }
  return { nodes, logs, edges, split: (focus?.edges ?? []).filter((e) => e.startsWith("b_")) };
}

export function GraphView({ graph, view, onSelectNode }: { graph: Graph; view: RunView; onSelectNode?: (id: string) => void }) {
  const [aspect, setAspect] = useState(1.9);
  const positions = useMemo(() => layout(graph, aspect), [graph, aspect]);
  const { fitView } = useReactFlow();
  const box = useRef<HTMLDivElement>(null);

  // the layout follows the panel's shape (in steps, so a resize does not re-layout every frame)
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width > 0 && height > 0) setAspect(Math.round((width / height) * 4) / 4);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // keep the whole graph in view: on load, when the graph or its layout changes and when the panel resizes
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const fit = () => requestAnimationFrame(() => void fitView({ padding: 0.05 }));
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, [graph, positions, fitView]);
  const allLinks = useMemo(() => links(graph), [graph]);

  const roots = new Map<string, string>();
  const symptoms = new Map<string, string>();
  const resolved = new Set<string>();
  for (const inc of Object.values(view.incidents)) {
    if (inc.state === "resolved") resolved.add(inc.root_node);
    else roots.set(inc.root_node, inc.verdict === "SUPPORTED_CAUSE" ? verdictLabel(inc.verdict).toLowerCase() : "anomaly");
  }
  for (const note of view.notes) {
    if (note.node && note.reason.includes("symptom of")) symptoms.set(note.node, "symptom");
  }
  const f = focusSets(view.focus);
  const path = affectedPath(graph, view);
  const fresh = freshAnomaly(view);
  const scored = new Set(view.tick?.scored_nodes ?? []);

  const nodes: Node[] = [
    ...graph.nodes.map((n): Node<MetricData> => {
      const z = fresh?.node === n.id ? Math.abs(fresh.z) : (view.tick?.max_abs_z[n.id] ?? Number.NaN);
      let tone: Tone = "normal";
      let tag: string | null = null;
      if (z >= view.thresholds.wiggle_z) tone = "wiggle";
      if (symptoms.has(n.id) && roots.size) {
        tone = "symptom";
        tag = "symptom";
      }
      if (z >= view.thresholds.alarm_z) tone = "alarm";
      if (roots.has(n.id)) {
        tone = "root";
        tag = roots.get(n.id) ?? null;
      } else if (resolved.has(n.id) && tone !== "alarm") {
        tone = "resolved";
        tag = "resolved";
      }
      const focus = f.nodes.has(n.id);
      if (focus && f.split.some((e) => e.startsWith(`b_${n.id}_`))) tag = "segment search";
      else if (focus) tag = tag ?? "checking";
      return {
        id: n.id,
        type: "metric",
        position: positions[n.id] ?? { x: 0, y: 0 },
        // the layout knows every box's size: without it React Flow hides a node until it is measured,
        // and after a restart the whole graph blinks out while the event burst is folded
        initialWidth: n.north_star ? NODE_W : SMALL_W,
        initialHeight: n.north_star ? NODE_H : SMALL_H,
        data: {
          node: n,
          z,
          history: view.zHistory[n.id] ?? [],
          heat: view.attention[n.id] ?? 0,
          tone,
          focus,
          tag,
          alarm: view.thresholds.alarm_z,
          scored: scored.has(n.id) || fresh?.node === n.id,
          path: path.has(n.id),
          recede: path.size > 0 && !path.has(n.id),
        },
        draggable: false,
      };
    }),
    ...graph.logs.map(
      (l): Node<LogData> => ({
        id: l.id,
        type: "log",
        position: positions[l.id] ?? { x: 0, y: 0 },
        initialWidth: LOG_W,
        initialHeight: LOG_H,
        data: { id: l.id, label: l.label, focus: f.logs.has(l.id), path: path.has(l.id), recede: path.size > 0 && !path.has(l.id) },
        draggable: false,
      }),
    ),
  ];

  const stars = new Set(graph.nodes.filter((n) => n.north_star).map((n) => n.id));
  const edges: Edge[] = allLinks.map((link) => {
    const status = link.edge ? (view.edges[link.edge.id]?.status ?? null) : null;
    // an edge is in focus when the step names it, or when the step touches both of its ends
    const named = link.edge ? f.edges.has(link.edge.id) && (f.nodes.size <= 1 || f.nodes.has(link.target) || f.nodes.has(link.source) || f.logs.has(link.source)) : false;
    const ends = f.nodes.has(link.target) && (f.nodes.has(link.source) || f.logs.has(link.source));
    const focused = named || ends;
    const onPath = path.has(link.source) && path.has(link.target);
    const styled = linkStyle(link, status, focused, onPath);
    // ratio definitions only while they matter; links between two compact metrics stay faint; an incident path
    // on screen pushes every other link back
    const quiet = !stars.has(link.source) && !stars.has(link.target);
    const opacity = focused || onPath ? 1 : path.size > 0 ? 0.15 : quiet ? 0.45 : 1;
    return {
      id: link.id,
      source: link.source,
      target: link.target,
      type: "default",
      hidden: !link.edge && !focused && !onPath,
      ...styled,
      style: { ...styled.style, opacity },
    };
  });

  return (
    <div ref={box} style={{ position: "absolute", inset: 0 }}>
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.08 }}
      minZoom={0.3}
      maxZoom={1.6}
      nodesConnectable={false}
      elementsSelectable={false}
      onNodeClick={(_, node) => onSelectNode?.(node.id)}
      proOptions={{ hideAttribution: true }}
      onInit={() => void fitView({ padding: 0.05 })}
    />
    </div>
  );
}
