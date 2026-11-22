import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ReceiptProvider } from "../../components/Receipts";
import { StyleProvider } from "../../fx";
import { AgentProvider } from "../../fx/workspace/agent";
import { api, follow, type ConnectionState } from "../../lib/api";
import { demoGraph, joinAgentDemo, useAgentDemo } from "../../lib/agentDemo";
import { emptyView, foldAll } from "../../lib/store";
import type { Graph } from "../../lib/types";
import "../../styles.css";
import { LiveFix } from "./index";

const params = new URLSearchParams(location.search);
const replayId = params.get("agentrun");
if (replayId) void joinAgentDemo(replayId);

function DevRoute() {
  const replay = useAgentDemo();
  const [view, setView] = useState(emptyView);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [rerun, setRerun] = useState(false);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [run, setRun] = useState(params.get("run"));
  useEffect(() => {
    let current = true;
    const graphRead = replayId ? demoGraph(replayId) : api.graph();
    void graphRead.then((result) => { if (current) setGraph(result); }, () => undefined);
    if (!replayId) void api.health().then((health) => { if (current) setRerun(Boolean(health.rerun)); }, () => undefined);
    const close = replayId ? undefined : follow({
      onReset: ({ stream, mode }) => setView(emptyView(stream, mode)),
      onEvents: (events) => setView((previous) => foldAll(previous, events)),
      onState: setConnection,
    });
    return () => { current = false; close?.(); };
  }, []);
  const replayView = useMemo(() => foldAll(emptyView(replay?.runId, "replay"), replay?.snapshot?.events ?? []), [replay?.snapshot, replay?.runId]);
  const active = replayId ? replayView : view;
  const incidentId = params.get("incident") ?? (run ? null : Object.values(active.incidents).at(-1)?.id ?? null);
  const selectRun = (id: string) => {
    const url = new URL(location.href);
    url.searchParams.set("run", id);
    url.searchParams.delete("incident");
    history.replaceState(null, "", url);
    setRun(id);
  };
  const incidentHref = (id: string) => {
    const url = new URL("/", location.href);
    url.searchParams.set("view", "incident");
    url.searchParams.set("incident", id);
    if (replayId) url.searchParams.set("agentrun", replayId);
    location.assign(url);
  };
  return (
    <main className="lf-dev">
      {!replayId && connection === "offline" && <p role="status">Argus API is offline. Reconnecting…</p>}
      {replay?.error && <p role="status">{replay.error}</p>}
      <AgentProvider stream={active.stream}>
        <ReceiptProvider rerunAvailable={rerun}>
          <LiveFix graph={graph} view={active} incidentId={incidentId} runId={run} onSelectRun={selectRun} onOpenIncident={incidentHref} />
        </ReceiptProvider>
      </AgentProvider>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><StyleProvider><DevRoute /></StyleProvider></StrictMode>);
