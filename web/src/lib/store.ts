// Folds the C5 event stream into the view state of Mission Control. Pure: `fold(state, event)`.

import type {
  Anomaly,
  ArgusEvent,
  EdgeStatus,
  EdgeTestResult,
  EvidenceRef,
  IncidentUpdatedPayload,
  Note,
  Segment,
  SkepticStepPayload,
  TickPayload,
  Thresholds,
  TrailStep,
} from "./types";

/** The watcher's lines until /health reports them (argus.watcher.detect: Z_OPEN, Z_PAIR, Z_ONSET). */
export const DEFAULT_THRESHOLDS: Thresholds = { alarm_z: 5, pair_z: 3.5, wiggle_z: 2 };
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
  thresholds: Thresholds;
  lastSeq: number;
  simTs: string | null;
  tick: TickPayload | null;
  ticks: number;
  firstHour: string | null;
  scoredSeries: number;
  wiggles: number;
  alarms: number;
  /** every scored |z| so far, in buckets of 0.1 (bucket 37 holds 3.7 <= |z| < 3.8) */
  zBuckets: Record<number, number>;
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

export function emptyView(
  stream: string | null = null,
  mode: RunView["mode"] = null,
  thresholds: Thresholds = DEFAULT_THRESHOLDS,
): RunView {
  return {
    stream,
    mode,
    thresholds,
    lastSeq: 0,
    simTs: null,
    tick: null,
    ticks: 0,
    firstHour: null,
    scoredSeries: 0,
    wiggles: 0,
    alarms: 0,
    zBuckets: {},
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

export function isRuledOut(decision: string): boolean {
  return decision.startsWith("ruled out") || decision.startsWith("refuted");
}

const unique = (xs: string[]) => [...new Set(xs)];

/**
 * What a step touches on the graph. A step may say so itself (`data.focus`); otherwise it is read from
 * the step's own data: the anomalous node, the logs it checks, the breakdowns it searches.
 */
export function focusOf(step: TrailStep, node: string | null, earlier: StepView[] = []): Focus {
  const explicit = step.data?.focus as Partial<Focus> | undefined;
  if (explicit) return { nodes: explicit.nodes ?? [], edges: explicit.edges ?? [], logs: explicit.logs ?? [] };
  const d = step.data ?? {};
  const nodes = node ? [node] : [];
  const edges: string[] = [];
  const logs: string[] = [];
  switch (step.kind) {
    case "identities":
      for (const i of (d.identities as { edge: string }[] | undefined) ?? []) edges.push(i.edge);
      break;
    case "calendar":
      logs.push("log_calendar");
      break;
    case "segment": {
      const path = d.path as { segment: Segment }[] | undefined;
      const last = path?.[path.length - 1];
      if (last && node) for (const dim of Object.keys(last.segment)) edges.push(`b_${node}_${dim}`);
      break;
    }
    case "events":
      for (const e of (d.events as EvidenceRef[] | undefined) ?? []) logs.push(e.log);
      break;
    case "holdout": {
      const e = d.event as EvidenceRef | undefined;
      if (e) logs.push(e.log);
      break;
    }
    case "impact":
      if (typeof d.node === "string") nodes.push(d.node);
      break;
    case "verdict":
      for (const s of earlier) {
        const e = s.step.data?.event as EvidenceRef | undefined;
        if (s.step.kind === "holdout" && e && !isRuledOut(s.step.decision)) logs.push(e.log);
      }
      break;
  }
  return { nodes: unique(nodes), edges: unique(edges), logs: unique(logs) };
}

export function fold(view: RunView, event: ArgusEvent): RunView {
  if (event.seq <= view.lastSeq) return view;
  const v: RunView = { ...view, lastSeq: event.seq, simTs: event.sim_ts };
  switch (event.type) {
    case "tick": {
      const p = event.payload;
      const zHistory = { ...v.zHistory };
      const zBuckets = { ...v.zBuckets };
      for (const node of p.scored_nodes) {
        const z = Math.abs(p.max_abs_z[node] ?? 0);
        zHistory[node] = [...(zHistory[node] ?? []), z].slice(-HISTORY);
        const bucket = Math.floor(z * 10 + 1e-9);
        zBuckets[bucket] = (zBuckets[bucket] ?? 0) + 1;
      }
      return {
        ...v,
        tick: p,
        ticks: v.ticks + 1,
        firstHour: v.firstHour ?? p.hour,
        scoredSeries: v.scoredSeries + p.scored_nodes.length,
        ...recount(zBuckets, v.thresholds),
        zBuckets,
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
      const node = v.anomalies.find((a) => a.id === p.anomaly_id)?.node ?? null;
      const earlier = v.steps.filter((s) => s.anomalyId === p.anomaly_id);
      return { ...v, steps: [...v.steps, step], focus: focusOf(p.step, node, earlier) };
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

/** Series-hours at or above the alarm line, and between the wiggle and the alarm line (thresholds are multiples of 0.1). */
export function recount(buckets: Record<number, number>, t: Thresholds): Pick<RunView, "wiggles" | "alarms"> {
  const alarmAt = Math.round(t.alarm_z * 10);
  const wiggleAt = Math.round(t.wiggle_z * 10);
  let wiggles = 0;
  let alarms = 0;
  for (const [bucket, n] of Object.entries(buckets)) {
    const b = Number(bucket);
    if (b >= alarmAt) alarms += n;
    else if (b >= wiggleAt) wiggles += n;
  }
  return { wiggles, alarms };
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
