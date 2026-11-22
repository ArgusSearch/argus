import { createContext, useContext, useMemo, type ReactNode } from "react";
import { AgentProvider, useAgent } from "../fx/workspace/agent";
import type { ConnectionState } from "./api";
import { selectMonitor, type MonitorState } from "./monitor";
import type { RunView } from "./store";
import type { Graph, Health } from "./types";

interface AppState {
  view: RunView;
  monitor: MonitorState;
}

const Context = createContext<AppState | null>(null);

interface ProviderProps {
  view: RunView;
  graph: Graph | null;
  health: Health | null;
  connection: ConnectionState;
  children: ReactNode;
}

export function AppStateProvider({ readAgent = false, ...props }: ProviderProps & { readAgent?: boolean }) {
  return (
    <AgentProvider stream={props.view.stream} asOf={props.view.simTs} active={readAgent}>
      <MonitorProvider {...props} />
    </AgentProvider>
  );
}

function MonitorProvider({ view, graph, health, connection, children }: ProviderProps) {
  const agent = useAgent();
  const value = useMemo(
    () => ({ view, monitor: selectMonitor(view, graph, health, connection, agent) }),
    [view, graph, health, connection, agent],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): AppState {
  const state = useContext(Context);
  if (!state) throw new Error("AppStateProvider is required for workspace views");
  return state;
}

/** The main workspace supplies current cues. Standalone agent tools can still render their own activity. */
export function useAgentAvatars() {
  const agent = useAgent();
  return useContext(Context)?.monitor.avatars ?? agent.avatars;
}
