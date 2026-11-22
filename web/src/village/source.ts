// Where the village's tape comes from. Two sources behind one shape (VillageTape), so the page never cares:
//   - a recorded run (S1, S4): a checked-in tape built from the recordings by tools/build-tapes.mjs, replayed
//     deterministically in the browser with no API at all;
//   - live: the API's C5 stream (GET /events, the Stage-2 investigation trail) plus, when lane A's agent is
//     enabled (GET /agent/health), its activity log (GET /agent/activity) and proposals (GET /agent/actions).

import { api, follow, type ConnectionState } from "../lib/api";
import { apiUrl } from "../lib/deployment";
import type { ArgusEvent, Incident } from "../lib/types";
import type { ActivityRecord, ProposalView, TapeIncident, TapePlacement, VillageTape } from "./types";

export type SourceId = "s1" | "s2" | "metric" | "s4" | "s5" | "live";
export type TapeId = Exclude<SourceId, "live">;

export const SOURCES: readonly { id: SourceId; label: string; hint: string }[] = [
  { id: "s1", label: "S1", hint: "Fault: PayCo payments fail on Android in Germany (recorded run)" },
  { id: "s2", label: "S2", hint: "Harmless change: a planned ad push, checked and logged, nobody woken (recorded run)" },
  { id: "metric", label: "New metric", hint: "New metrics place themselves in the map: placed, held when two formulas fit, rejected when the SQL is wrong (recorded)" },
  { id: "s4", label: "S4", hint: "Fault: the ad pacer overspends in DE and FR, and the fix waits for your approval (recorded run)" },
  { id: "s5", label: "S5", hint: "The whole market dips (expected), and a routing fault hides inside it (recorded run)" },
  { id: "live", label: "Live", hint: "Follow the API's event stream and the agent's activity log" },
];

const TAPES = import.meta.glob<string>("./tapes/*.json", { query: "?url", import: "default" });

/** The URL of a checked-in tape, or null when the scenario has none. */
export async function tapeUrl(scenario: string): Promise<string | null> {
  const load = TAPES[`./tapes/${scenario}.json`];
  return load ? load() : null;
}

export async function loadTape(scenario: TapeId, signal?: AbortSignal): Promise<VillageTape> {
  const url = await tapeUrl(scenario);
  if (!url) throw new Error(`no tape for ${scenario}`);
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`tape ${scenario}: ${res.status}`);
  return (await res.json()) as VillageTape;
}

/** Which source a page load starts on: ?village=s1|s2|s4|s5|live, else the S4 replay (the demo story). */
export function initialSource(search: string): SourceId {
  const asked = new URLSearchParams(search).get("village");
  return SOURCES.some((s) => s.id === asked) ? (asked as SourceId) : "s4";
}

// ---------------------------------------------------------------- live

interface AgentHealth {
  enabled: boolean;
  mode: string;
}

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(apiUrl(path));
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

function emptyLive(): VillageTape {
  return { version: 1, scenario: "live", title: "Live", source: "API stream", labels: {}, incidents: [], events: [], activity: [], actions: [], continuations: {} };
}

/**
 * Follows the API and calls `onTape` with the growing tape (a new object on every change). Returns the stop
 * function. A replay restart on the server resets the tape.
 */
export function followLive(onTape: (tape: VillageTape) => void, onState: (state: ConnectionState, agent: boolean) => void): () => void {
  let tape = emptyLive();
  let stopped = false;
  let agent = false;
  let connection: ConnectionState = "connecting";
  let activitySince = 0;
  let timer = 0;
  const askedIncidents = new Set<string>();

  const publish = () => {
    if (!stopped) onTape(tape);
  };
  const labels = () =>
    api.graph().then(
      (g) => {
        tape = { ...tape, labels: Object.fromEntries(g.nodes.map((n) => [n.id, n.label])) };
        publish();
      },
      () => undefined,
    );

  const incident = (id: string) => {
    if (askedIncidents.has(id)) return;
    askedIncidents.add(id);
    getJson<Incident>(`/incidents/${encodeURIComponent(id)}`).then((inc) => {
      if (!inc || stopped) return;
      const entry: TapeIncident = { id: inc.id, title: inc.title, segment: inc.segment, suggested_action: inc.findings?.suggested_action ?? null };
      tape = { ...tape, incidents: [...tape.incidents.filter((i) => i.id !== id), entry] };
      publish();
    });
  };

  const pollAgent = async () => {
    if (stopped) return;
    const page = await getJson<{ records: ActivityRecord[] }>(`/agent/activity?since=${activitySince}`);
    if (page?.records.length) {
      activitySince = page.records[page.records.length - 1].seq;
      tape = { ...tape, activity: [...tape.activity, ...page.records] };
      if (page.records.some((r) => r.kind.startsWith("action_"))) {
        const actions = await getJson<ProposalView[]>("/agent/actions");
        if (actions) tape = { ...tape, actions };
      }
      publish();
    }
    if (!stopped) timer = window.setTimeout(pollAgent, 1500);
  };

  // new metrics placing themselves (lane H): GET /graph/metrics, while the route exists
  interface Placement {
    metric: { name: string; description: string };
    placed_as: TapePlacement["placed_as"];
    summary: string;
    definition: string;
    as_of: string;
    certificate: { tried: string[]; passed: string[]; uncertain: string[]; receipts: string[] };
  }
  let placed = 0;
  const pollMetrics = async () => {
    if (stopped) return;
    const state = await getJson<{ placements: Placement[] }>("/graph/metrics");
    if (state?.placements && state.placements.length !== placed) {
      placed = state.placements.length;
      tape = {
        ...tape,
        placements: state.placements.map((p) => ({
          metric: p.metric,
          placed_as: p.placed_as,
          summary: p.summary,
          definition: p.definition,
          as_of: p.as_of,
          tried: p.certificate.tried,
          passed: p.certificate.passed,
          uncertain: p.certificate.uncertain,
          receipts: p.certificate.receipts,
        })),
      };
      publish();
    }
    if (!stopped && state) metricsTimer = window.setTimeout(pollMetrics, 3000);
  };
  let metricsTimer = 0;
  pollMetrics();

  getJson<AgentHealth>("/agent/health").then((h) => {
    agent = Boolean(h?.enabled);
    onState(connection, agent);
    if (agent) pollAgent();
  });
  labels();

  const stop = follow({
    onReset: () => {
      tape = { ...emptyLive(), labels: tape.labels };
      askedIncidents.clear();
      activitySince = 0;
      labels();
      publish();
    },
    onEvents: (events: ArgusEvent[]) => {
      tape = { ...tape, events: [...tape.events, ...events] };
      for (const e of events) if (e.type === "incident_updated") incident(e.payload.id);
      publish();
    },
    onState: (state) => {
      connection = state;
      onState(state, agent);
    },
  });

  return () => {
    stopped = true;
    window.clearTimeout(timer);
    window.clearTimeout(metricsTimer);
    stop();
  };
}

/** Sends your decision on a real agent proposal. Resolves to the proposal's new state, or throws the API's reason. */
export async function decideLive(proposal: ProposalView, decision: "approve" | "deny"): Promise<ProposalView> {
  const key = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  const res = await fetch(apiUrl(`/agent/actions/${encodeURIComponent(proposal.id)}/${decision}`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ digest: proposal.digest, idempotency_key: key }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return (await res.json()) as ProposalView;
}
