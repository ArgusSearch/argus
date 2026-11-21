// The agent presentation of the demo playback (lane F, docs/pitch/agent-scene.md): `POST /demo/start` with
// `variant: "agent"` returns a presentation `run_id`; `GET /demo/snapshot?run_id=` holds the C5 events and the
// incidents visible at the presentation's clock; every agent and evidence route takes the same `run_id`. At
// `awaiting_approval` the clock holds until the operator approves or denies the proposal in the app.
// One presentation at a time, shared by the whole page through this small store.

import { useSyncExternalStore } from "react";
import { ApiError } from "./api";
import type { ArgusEvent, Incident } from "./types";

export type AgentDemoStatus = "idle" | "playing" | "paused" | "awaiting_approval" | "completed";

export interface AgentDemoState {
  version: 1;
  run_id: string | null;
  scenario: "s1" | "s4" | null;
  status: AgentDemoStatus;
  speed: number | null;
  elapsed_ms: number;
  duration_ms: number | null;
  beat_index: number | null;
  beat_count: number;
  variant?: "agent" | "legacy";
  decision?: "approve" | "deny" | null;
  sim_ts?: string;
  through_seq?: number;
}

export interface AgentSnapshot {
  state: AgentDemoState;
  events: ArgusEvent[];
  incidents: Incident[];
}

export interface AgentDemo {
  runId: string;
  snapshot: AgentSnapshot | null;
  error: string | null;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return (await res.json()) as T;
}

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

/** Whether this API serves the agent presentation (its route table lists `/demo/snapshot`). */
export async function agentDemoAvailable(): Promise<boolean> {
  try {
    const table = await call<{ paths?: Record<string, unknown> }>("/openapi.json");
    return Boolean(table.paths && "/demo/snapshot" in table.paths);
  } catch {
    return false;
  }
}

/* ------------------------------------------------------------------ store */

type Listener = () => void;
const listeners = new Set<Listener>();
let current: AgentDemo | null = null;
let timer = 0;
const POLL_MS = 600;

function set(next: AgentDemo | null) {
  current = next;
  for (const l of [...listeners]) l();
}

export function useAgentDemo(): AgentDemo | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
    () => null,
  );
}

/** The presentation's run id, for the agent and evidence routes (null outside a presentation). */
export function demoRunId(): string | null {
  return current?.runId ?? null;
}

/** `path` with the presentation's `run_id` appended, when one is playing. */
export function withRun(path: string): string {
  const id = demoRunId();
  if (!id) return path;
  return `${path}${path.includes("?") ? "&" : "?"}run_id=${encodeURIComponent(id)}`;
}

/** The incidents the presentation shows right now (null outside a presentation). */
export function demoIncidents(): Incident[] | null {
  return current?.snapshot?.incidents ?? null;
}

async function poll() {
  window.clearTimeout(timer);
  const run = current;
  if (!run) return;
  try {
    const snapshot = await call<AgentSnapshot>(`/demo/snapshot?run_id=${encodeURIComponent(run.runId)}`);
    if (current?.runId !== run.runId) return;
    // the snapshot only grows: keep the object when nothing moved, so the page does not re-render for nothing
    const prev = current.snapshot;
    const same = prev && prev.events.length === snapshot.events.length && prev.state.status === snapshot.state.status && prev.incidents.length === snapshot.incidents.length && JSON.stringify(prev.incidents.map((i) => i.state)) === JSON.stringify(snapshot.incidents.map((i) => i.state));
    if (!same || current.error) set({ runId: run.runId, snapshot: same ? prev : snapshot, error: null });
  } catch (e) {
    if (current?.runId !== run.runId) return;
    // 204/409: the presentation was replaced or finished elsewhere
    set({ ...current, error: (e as Error).message });
  }
  if (current?.runId === run.runId) timer = window.setTimeout(() => void poll(), POLL_MS);
}

/** Starts a new agent presentation (replaces any running one on the server) and follows it. */
export async function startAgentDemo(scenario: "s1" | "s4" = "s4", speed = 1): Promise<void> {
  const state = await call<AgentDemoState>("/demo/start", post({ scenario, variant: "agent", speed }));
  if (!state.run_id) throw new Error("the server did not start an agent presentation");
  set({ runId: state.run_id, snapshot: null, error: null });
  await poll();
}

/** Follows a presentation someone else started (a capture script, another tab). */
export async function joinAgentDemo(runId: string): Promise<void> {
  set({ runId, snapshot: null, error: null });
  await poll();
}

export async function controlAgentDemo(action: "pause" | "resume" | "skip" | "restart"): Promise<void> {
  const run = current;
  if (!run) return;
  const state = await call<AgentDemoState>(`/demo/control?run_id=${encodeURIComponent(run.runId)}`, post({ action }));
  if (action === "restart" && state.run_id && state.run_id !== run.runId) set({ runId: state.run_id, snapshot: null, error: null });
  await poll();
}

/** Leaves the presentation in this page (the server keeps it); the page goes back to the live stream. */
export function leaveAgentDemo() {
  window.clearTimeout(timer);
  set(null);
}
