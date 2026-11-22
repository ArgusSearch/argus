import { useEffect, useState } from "react";
import { analysisHref, navigateWorkspaceURL } from "../../analysis/shell/location";
import { agentDemoAvailable, controlAgentDemo, joinAgentDemo, leaveAgentDemo, startAgentDemo, useAgentDemo, type AgentDemoStatus } from "../../lib/agentDemo";

const STATUS: Record<AgentDemoStatus, string> = {
  idle: "Ready",
  playing: "Playing",
  paused: "Paused",
  awaiting_approval: "Waiting for your approval",
  completed: "Done",
};

let autostarted = false;

export function AgentRunControls() {
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

  if (!available || !demo) return error ? <span role="alert">{error}</span> : null;
  const state = demo.snapshot?.state;
  return (
    <div className="controls" aria-label="Sealed agent run">
      <span role="status">{state ? STATUS[state.status] : "Starting…"}</span>
      {state?.status === "awaiting_approval" && <button className="ctl" onClick={() => navigateWorkspaceURL(analysisHref(null))}>Decide now</button>}
      {state?.status === "playing" && <button className="ctl" onClick={() => act(() => controlAgentDemo("pause"))}>Pause</button>}
      {state?.status === "paused" && <button className="ctl" onClick={() => act(() => controlAgentDemo("resume"))}>Resume</button>}
      <button className="ctl" onClick={() => act(() => controlAgentDemo("restart"))}>Restart</button>
      <button className="ctl" onClick={() => leaveAgentDemo()} title="Return to the live run">Leave</button>
      {(error || demo.error) && <span role="alert">{error ?? demo.error}</span>}
    </div>
  );
}
