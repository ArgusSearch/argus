// Folds the C5 event stream into the view state of Mission Control. Pure: `fold(state, event)`.

import type {
  Anomaly,
  ArgusEvent,
  EdgeStatus,
  EdgeTestResult,
  IncidentUpdatedPayload,
  Note,
  SkepticStepPayload,
  TickPayload,
  TrailStep,
} from "./types";

export const ALARM_Z = 4;
export const WIGGLE_Z = 2;
const HISTORY = 36;

export interface Focus {
  nodes: string[];
  edges: string[];
  logs: string[];
}

export interface StepView {
  seq: number;
  simTs: string;
  anomalyId: string;
  incidentId: string | null;
  step: TrailStep;
}

export interface EdgeChange {
  seq: number;
  simTs: string;
  edge: string;
  from: EdgeStatus | null;
  to: EdgeStatus;
  result: EdgeTestResult;
}

export interface IncidentView extends IncidentUpdatedPayload {
  firstSeq: number;
  lastSeq: number;
  updatedAt: string;
  openedAt: string;
}

export type FeedItem =
  | { kind: "incident"; id: string; seq: number }
  | { kind: "note"; note: Note; seq: number }
  | { kind: "edges"; seq: number; simTs: string; changes: EdgeChange[] };

export interface RunView {
  stream: string | null;
  mode: "replay" | "live" | null;
  lastSeq: number;
  simTs: string | null;
  tick: TickPayload | null;
  ticks: number;
  firstHour: string | null;
  scoredSeries: number;
  wiggles: number;
  alarms: number;
  zHistory: Record<string, number[]>;
  attention: Record<string, number>;
  edges: Record<string, { status: EdgeStatus; result: EdgeTestResult }>;
  edgeChanges: EdgeChange[];
  anomalies: Anomaly[];
  incidents: Record<string, IncidentView>;
  notes: Note[];
  steps: StepView[];
  skeptic: (SkepticStepPayload & { seq: number })[];
  focus: Focus | null;
  feed: FeedItem[];
}

export function emptyView(stream: string | null = null, mode: RunView["mode"] = null): RunView {
  return {
    stream,
    mode,
    lastSeq: 0,
    simTs: null,
    tick: null,
    ticks: 0,
    firstHour: null,
    scoredSeries: 0,
    wiggles: 0,
    alarms: 0,
    zHistory: {},
    attention: {},
    edges: {},
    edgeChanges: [],
    anomalies: [],
    incidents: {},
    notes: [],
    steps: [],
    skeptic: [],
    focus: null,
    feed: [],
  };
}

function focusOf(step: TrailStep): Focus {
  const f = (step.data?.focus ?? {}) as Partial<Focus>;
  return { nodes: f.nodes ?? [], edges: f.edges ?? [], logs: f.logs ?? [] };
}

export function fold(view: RunView, event: ArgusEvent): RunView {
  if (event.seq <= view.lastSeq) return view;
  const v: RunView = { ...view, lastSeq: event.seq, simTs: event.sim_ts };
  switch (event.type) {
    case "tick": {
      const p = event.payload;
      const zHistory = { ...v.zHistory };
      let wiggles = 0;
      let alarms = 0;
      for (const node of p.scored_nodes) {
        const z = p.max_abs_z[node] ?? 0;
        zHistory[node] = [...(zHistory[node] ?? []), z].slice(-HISTORY);
        if (z >= ALARM_Z) alarms += 1;
        else if (z >= WIGGLE_Z) wiggles += 1;
      }
      return {
        ...v,
        tick: p,
        ticks: v.ticks + 1,
        firstHour: v.firstHour ?? p.hour,
        scoredSeries: v.scoredSeries + p.scored_nodes.length,
        wiggles: v.wiggles + wiggles,
        alarms: v.alarms + alarms,
        zHistory,
        // a new tick ends the walk of the previous investigation
        focus: null,
      };
    }
    case "attention":
      return { ...v, attention: event.payload.scores };
    case "edge_status": {
      const p = event.payload;
      const change: EdgeChange = {
        seq: event.seq,
        simTs: event.sim_ts,
        edge: p.edge,
        from: p.old_status,
        to: p.new_status,
        result: p.result,
      };
      const feed = [...v.feed];
      const last = feed[feed.length - 1];
      if (last && last.kind === "edges" && last.simTs === event.sim_ts) {
        feed[feed.length - 1] = { ...last, seq: event.seq, changes: [...last.changes, change] };
      } else {
        feed.push({ kind: "edges", seq: event.seq, simTs: event.sim_ts, changes: [change] });
      }
      return {
        ...v,
        edges: { ...v.edges, [p.edge]: { status: p.new_status, result: p.result } },
        edgeChanges: [...v.edgeChanges, change],
        feed,
      };
    }
    case "graph_changed": {
      const p = event.payload;
      if (!p.edge || !p.new_status) return v;
      const prev = v.edges[p.edge];
      const result: EdgeTestResult = prev?.result ?? {
        ran_at: p.sim_ts,
        passed: null,
        median_rel: null,
        p95_rel: null,
        max_rel_err: null,
        hours: 0,
        receipts: p.receipts,
        note: p.reason,
      };
      const change: EdgeChange = {
        seq: event.seq,
        simTs: event.sim_ts,
        edge: p.edge,
        from: p.old_status,
        to: p.new_status,
        result: { ...result, note: p.reason || result.note },
      };
      return {
        ...v,
        edges: { ...v.edges, [p.edge]: { status: p.new_status, result } },
        edgeChanges: [...v.edgeChanges, change],
        feed: [...v.feed, { kind: "edges", seq: event.seq, simTs: event.sim_ts, changes: [change] }],
      };
    }
    case "anomaly_opened":
      return { ...v, anomalies: [...v.anomalies, event.payload], focus: { nodes: [event.payload.node], edges: [], logs: [] } };
    case "investigation_step": {
      const p = event.payload;
      const step: StepView = {
        seq: event.seq,
        simTs: event.sim_ts,
        anomalyId: p.anomaly_id,
        incidentId: p.incident_id,
        step: p.step,
      };
      return { ...v, steps: [...v.steps, step], focus: focusOf(p.step) };
    }
    case "skeptic_step":
      return { ...v, skeptic: [...v.skeptic, { ...event.payload, seq: event.seq }] };
    case "incident_updated": {
      const p = event.payload;
      const prev = v.incidents[p.id];
      const incident: IncidentView = {
        ...p,
        firstSeq: prev?.firstSeq ?? event.seq,
        lastSeq: event.seq,
        updatedAt: event.sim_ts,
        openedAt: prev?.openedAt ?? event.sim_ts,
      };
      const feed = v.feed.filter((item) => !(item.kind === "incident" && item.id === p.id));
      feed.push({ kind: "incident", id: p.id, seq: event.seq });
      return { ...v, incidents: { ...v.incidents, [p.id]: incident }, feed };
    }
    case "note_logged":
      return {
        ...v,
        notes: [...v.notes, event.payload],
        feed: [...v.feed, { kind: "note", note: event.payload, seq: event.seq }],
      };
    default:
      return v;
  }
}

export function foldAll(view: RunView, events: ArgusEvent[]): RunView {
  return events.reduce(fold, view);
}

/** Nodes that the open incidents name as root or symptom (for the graph colors). */
export function incidentNodes(view: RunView): { roots: Set<string>; open: boolean } {
  const roots = new Set<string>();
  let open = false;
  for (const inc of Object.values(view.incidents)) {
    if (inc.state !== "resolved") {
      roots.add(inc.root_node);
      open = true;
    }
  }
  return { roots, open };
}
