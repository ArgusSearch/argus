// The agent's state for every page of the workspace: one probe (GET /agent/health) and one poller for the whole
// app, shared through context, so the overview, the incident page, the activity page and Ask Argus all show the
// same proposals and the same activity. While the routes are not mounted, `enabled` is false and every surface
// falls back to what the run itself carries (the findings' suggested action, the C5 investigation).

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useApprovalCount } from "./approvals";
import { agentApi, settling, type ActivityRecord, type AgentHealth, type ProposalView, type RunSummary } from "../../lib/agent";
import { useAgentDemo } from "../../lib/agentDemo";

export interface AgentState {
  enabled: boolean;
  health: AgentHealth | null;
  records: ActivityRecord[];
  proposals: ProposalView[];
  runs: RunSummary[];
  /** re-read proposals and runs now (after a decision) */
  refresh: () => void;
  /** replace one proposal with the version a decision returned */
  put: (p: ProposalView) => void;
}

const EMPTY: AgentState = { enabled: false, health: null, records: [], proposals: [], runs: [], refresh: () => undefined, put: () => undefined };
const Ctx = createContext<AgentState>(EMPTY);

export function useAgent(): AgentState {
  return useContext(Ctx);
}

/** Decisions people made: approved or denied proposals (operator decisions), plus approvals kept in this browser. */
export function useHumanActions(stream: string | null): number {
  const agent = useAgent();
  const local = useApprovalCount(stream);
  const decided = agent.enabled ? agent.proposals.filter((p) => p.decision !== null).length : 0;
  return decided + local;
}

/** The proposal for an incident (the newest one), if the agent made one. */
export function proposalFor(state: AgentState, incident: string): ProposalView | null {
  return [...state.proposals].reverse().find((p) => p.incident_ref === incident) ?? null;
}

const ACTIVITY_MS = 1500;
const ACTIONS_MS = 2000;
const KEEP = 600;

export function AgentProvider({ stream, children }: { stream: string | null; children: ReactNode }) {
  const [health, setHealth] = useState<AgentHealth | null>(null);
  const [records, setRecords] = useState<ActivityRecord[]>([]);
  const [proposals, setProposals] = useState<ProposalView[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const cursor = useRef({ stream: null as string | null, seq: 0 });
  const [tick, setTick] = useState(0);
  // a replay server's own agent is off, but during the agent presentation the same routes answer for its run
  const presenting = useAgentDemo() !== null;
  const enabled = Boolean(health && (health.enabled || presenting));

  // the probe: once per stream (routes only appear with a restarted API, which starts a new stream)
  useEffect(() => {
    let live = true;
    void agentApi.health().then((h) => live && setHealth(h));
    return () => {
      live = false;
    };
  }, [stream]);

  // activity: incremental from the last seq; a new stream starts the log over
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let timer = 0;
    const pull = async () => {
      if (!document.hidden) {
        try {
          const res = await agentApi.activity(cursor.current.stream === null ? 0 : cursor.current.seq);
          if (!live) return;
          const fresh = res.stream !== cursor.current.stream;
          const last = res.records[res.records.length - 1]?.seq;
          cursor.current = { stream: res.stream, seq: last ?? (fresh ? 0 : cursor.current.seq) };
          if (fresh) setRecords(res.records.slice(-KEEP));
          else if (res.records.length) setRecords((r) => [...r, ...res.records.filter((x) => !r.some((y) => y.seq === x.seq))].slice(-KEEP));
        } catch {
          /* the next pull tries again */
        }
      }
      if (live) timer = window.setTimeout(pull, ACTIVITY_MS);
    };
    void pull();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [enabled, stream]);

  // proposals and runs
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let timer = 0;
    const pull = async () => {
      if (!document.hidden) {
        const [p, r] = await Promise.allSettled([agentApi.actions(), agentApi.runs()]);
        if (!live) return;
        if (p.status === "fulfilled") setProposals(p.value);
        if (r.status === "fulfilled") setRuns(r.value);
      }
      if (live) timer = window.setTimeout(pull, ACTIONS_MS);
    };
    void pull();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [enabled, stream, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const put = useCallback((p: ProposalView) => {
    setProposals((all) => (all.some((x) => x.id === p.id) ? all.map((x) => (x.id === p.id ? p : x)) : [...all, p]));
    if (settling(p.state)) setTick((t) => t + 1);
  }, []);

  const value = useMemo<AgentState>(() => ({ enabled, health, records, proposals, runs, refresh, put }), [enabled, health, records, proposals, runs, refresh, put]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
