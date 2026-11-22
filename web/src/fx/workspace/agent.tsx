// The agent's state for every page of the workspace: one probe (GET /agent/health) and one poller for the whole
// app, shared through context, so the overview, the incident page, the activity page and Ask Argus all show the
// same proposals and the same activity. While the routes are not mounted, `enabled` is false and every surface
// falls back to what the run itself carries (the findings' suggested action, the C5 investigation).

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useApprovalCount } from "./approvals";
import { pendingProposals } from "../../agent-ui/activity";
import { useWaitingTitle } from "../../agent-ui/hooks";
import { agentApi, settling, type ActivityRecord, type AgentHealth, type ProposalView, type RunSummary } from "../../lib/agent";
import { useAgentDemo } from "../../lib/agentDemo";
import { pollEvents } from "../../lib/deployment";
import type { RunView } from "../../lib/store";
import { avatarCues, WORK_CUE_MS, type AvatarCues } from "../../village/avatars/state";

export interface AgentState {
  scope: string | null;
  enabled: boolean;
  health: AgentHealth | null;
  records: ActivityRecord[];
  proposals: ProposalView[];
  runs: RunSummary[];
  avatars: AvatarCues;
  /** proposals waiting for a person's decision (the sidebar and the tab title count them) */
  waiting: number;
  /** re-read proposals and runs now (after a decision) */
  refresh: () => void;
  /** replace one proposal with the version a decision returned */
  put: (p: ProposalView) => void;
}

const EMPTY: AgentState = { scope: null, enabled: false, health: null, records: [], proposals: [], runs: [], avatars: {}, waiting: 0, refresh: () => undefined, put: () => undefined };
const EMPTY_ACTIVITY = { records: [] as ActivityRecord[], until: new Map<number, number>() };
const Ctx = createContext<AgentState>(EMPTY);

export function useAgent(): AgentState {
  return useContext(Ctx);
}

/** Decisions people made: approved or denied proposals (operator decisions), plus approvals kept in this browser. */
export function useHumanActions(view: Pick<RunView, "stream" | "mode">): number {
  const agent = useAgent();
  const local = useApprovalCount(view.stream);
  const decided = agent.enabled ? agent.proposals.filter((p) => p.decision !== null).length : 0;
  return decided + (view.mode === "replay" ? local : 0);
}

/** The proposal for an incident (the newest one), if the agent made one. */
export function proposalFor(state: AgentState, incident: string): ProposalView | null {
  return [...state.proposals].reverse().find((p) => p.incident_ref === incident) ?? null;
}

const ACTIVITY_MS = pollEvents ? 2500 : 1500;
const ACTIONS_MS = pollEvents ? 3000 : 2000;
const KEEP = 600;

export function AgentProvider({ stream, children }: { stream: string | null; children: ReactNode }) {
  const [health, setHealth] = useState<AgentHealth | null>(null);
  const [activity, setActivity] = useState(EMPTY_ACTIVITY);
  const [avatarClock, setAvatarClock] = useState(0);
  const [proposals, setProposals] = useState<ProposalView[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [tick, setTick] = useState(0);
  // a replay server's own agent is off, but during the agent presentation the same routes answer for its run
  const demoId = useAgentDemo()?.runId;
  const scope = demoId ? `demo:${demoId}` : stream;
  const activeScope = useRef(scope);
  useLayoutEffect(() => {
    activeScope.current = scope;
  }, [scope]);
  const [dataScope, setDataScope] = useState(scope);
  if (dataScope !== scope) {
    setDataScope(scope);
    setActivity(EMPTY_ACTIVITY);
    setProposals([]);
    setRuns([]);
  }
  const enabled = Boolean(health && (health.enabled || demoId));

  // the probe: once per stream (routes only appear with a restarted API, which starts a new stream)
  useEffect(() => {
    let live = true;
    void agentApi.health().then((h) => live && setHealth(h));
    return () => {
      live = false;
    };
  }, [stream]);

  // Activity is incremental within one source. A new demo gets its own cursor even if the live stream never changed.
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let timer = 0;
    let cursor = { stream: null as string | null, seq: 0 };
    const pull = async () => {
      if (!document.hidden) {
        try {
          let res = await agentApi.activity(cursor.seq);
          if (!live || activeScope.current !== scope) return;
          const fresh = res.stream !== cursor.stream;
          if (fresh && cursor.seq > 0) res = await agentApi.activity(0);
          if (!live || activeScope.current !== scope) return;
          const previousSeq = cursor.seq;
          const last = res.records[res.records.length - 1]?.seq;
          cursor = { stream: res.stream, seq: last ?? (fresh ? 0 : cursor.seq) };
          if (fresh) setActivity({ records: res.records.slice(-KEEP), until: new Map() });
          else if (res.records.length) {
            const added = res.records.filter((record) => record.seq > previousSeq);
            const now = Date.now();
            setActivity((current) => {
              const until = new Map([...current.until].filter(([, deadline]) => deadline > now));
              for (const record of added) until.set(record.seq, now + WORK_CUE_MS);
              return { records: [...current.records, ...added].slice(-KEEP), until };
            });
          }
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
  }, [enabled, scope]);

  // proposals and runs
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let timer = 0;
    const pull = async () => {
      if (!document.hidden) {
        const [p, r] = await Promise.allSettled([agentApi.actions(), agentApi.runs()]);
        if (!live || activeScope.current !== scope) return;
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
  }, [enabled, scope, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const put = useCallback((p: ProposalView) => {
    if (activeScope.current !== scope) return;
    setProposals((all) => (all.some((x) => x.id === p.id) ? all.map((x) => (x.id === p.id ? p : x)) : [...all, p]));
    if (settling(p.state)) setTick((t) => t + 1);
  }, [scope]);

  const waiting = enabled ? pendingProposals(proposals).length : 0;
  useWaitingTitle(waiting);
  const { roles: avatars, nextExpiry } = useMemo(
    () => avatarCues(activity.records, proposals, runs, activity.until, Math.max(avatarClock, Date.now())),
    [activity, avatarClock, proposals, runs],
  );
  useEffect(() => {
    if (!Number.isFinite(nextExpiry)) return;
    const timer = window.setTimeout(() => setAvatarClock(Date.now()), Math.max(1, nextExpiry - Date.now()));
    return () => window.clearTimeout(timer);
  }, [nextExpiry, avatarClock]);
  const value = useMemo<AgentState>(
    () => ({ scope, enabled, health, records: activity.records, proposals, runs, avatars, waiting, refresh, put }),
    [scope, enabled, health, activity.records, proposals, runs, avatars, waiting, refresh, put],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
