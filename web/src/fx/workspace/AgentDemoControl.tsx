// The agent presentation's control in the sidebar: start it, see where it stands (playing, waiting for your
// approval, done), pause, resume, restart or leave it. Shown only where the API serves the presentation.
// `?agentdemo=s4` (or `s1`) starts one on load, `&agentspeed=` sets its speed; `?agentrun=<run_id>` follows a
// presentation a capture script started.

import { useEffect, useState } from "react";
import { agentDemoAvailable, controlAgentDemo, joinAgentDemo, leaveAgentDemo, startAgentDemo, useAgentDemo, type AgentDemoStatus } from "../../lib/agentDemo";
import { dayLabel, hhmm } from "../../lib/format";
import { go } from "../nav";
import { Pill } from "./ui";
import type { Tone } from "./plain";

const STATUS: Record<AgentDemoStatus, { word: string; tone: Tone }> = {
  idle: { word: "Ready", tone: "muted" },
  playing: { word: "Playing", tone: "probe" },
  paused: { word: "Paused", tone: "watch" },
  awaiting_approval: { word: "Waiting for your approval", tone: "alarm" },
  completed: { word: "Done", tone: "ok" },
};

let autostarted = false;

export function AgentDemoControl() {
  const demo = useAgentDemo();
  const [available, setAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void agentDemoAvailable().then((ok) => {
      if (!live) return;
      setAvailable(ok);
      if (!ok || autostarted) return;
      autostarted = true;
      const q = new URLSearchParams(window.location.search);
      const run = q.get("agentrun");
      const scenario = q.get("agentdemo");
      const speed = Number(q.get("agentspeed"));
      if (run) void joinAgentDemo(run).catch((e: Error) => setError(e.message));
      else if (scenario === "s1" || scenario === "s4" || scenario === "1")
        void startAgentDemo(scenario === "s1" ? "s1" : "s4", Number.isFinite(speed) && speed > 0 ? speed : 1).catch((e: Error) => setError(e.message));
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!available) return;
    const restore = () => {
      const run = new URLSearchParams(window.location.search).get("agentrun");
      if (run && run !== demo?.runId) void joinAgentDemo(run);
      else if (!run && demo) leaveAgentDemo();
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, [available, demo?.runId]);

  const act = (fn: () => Promise<void>) => {
    setError(null);
    fn().catch((e: Error) => setError(e.message));
  };

  if (!available) return null;
  const state = demo?.snapshot?.state;
  const status = state ? STATUS[state.status] : null;
  return (
    <section className="fx-demo" aria-label="agent demo">
      <span className="fx-hud">Agent demo</span>
      {!demo && (
        <button className="btn primary" onClick={() => act(() => startAgentDemo("s4", 1))}>
          ▶ Play the S4 agent run
        </button>
      )}
      {demo && (
        <>
          <div className="fx-demo-state">
            {status ? <Pill tone={status.tone}>{status.word}</Pill> : <Pill tone="muted">Starting…</Pill>}
            {state?.sim_ts && (
              <span className="mono">
                {dayLabel(state.sim_ts)} {hhmm(state.sim_ts)}
              </span>
            )}
          </div>
          {state?.status === "awaiting_approval" && (
            <button className="btn primary" onClick={() => go("dashboard")}>
              Decide now
            </button>
          )}
          <div className="fx-demo-ctl">
            {state?.status === "playing" && (
              <button className="btn" onClick={() => act(() => controlAgentDemo("pause"))}>
                Pause
              </button>
            )}
            {state?.status === "paused" && (
              <button className="btn" onClick={() => act(() => controlAgentDemo("resume"))}>
                Resume
              </button>
            )}
            <button className="btn" onClick={() => act(() => controlAgentDemo("restart"))}>
              Restart
            </button>
            <button className="btn" onClick={() => leaveAgentDemo()} title="Back to the live run (the presentation keeps its place on the server)">
              Leave
            </button>
          </div>
        </>
      )}
      {(error || demo?.error) && <p className="ws-act-error">{error ?? demo?.error}</p>}
    </section>
  );
}
