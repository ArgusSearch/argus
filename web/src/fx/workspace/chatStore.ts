// Whether the chat window is open, and which agent's thread someone asked to see. A tiny store of its own so any
// surface (the sidebar, an agent's avatar, the village) can open the chat without importing the window.

import { useSyncExternalStore } from "react";
import type { AgentRole } from "../../lib/agent";

type Listener = () => void;
const listeners = new Set<Listener>();
const OPEN_KEY = "argus.chat.open";

export function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = typeof localStorage === "undefined" ? null : localStorage.getItem(key);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

export function writeFlag(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* storage blocked: the choice lasts for this page */
  }
}

// the window stays open across pages and reloads once opened
let open = readFlag(OPEN_KEY, false);
/** the latest request to talk to one agent (null: Argus as a whole); `seq` makes a repeated click a new request */
let request: { agent: AgentRole | null; seq: number } | null = null;

const notify = () => {
  for (const l of [...listeners]) l();
};

const subscribe = (l: Listener) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};

export function isAskOpen(): boolean {
  return open;
}

export function setAskOpen(next: boolean) {
  if (next === open) return;
  open = next;
  writeFlag(OPEN_KEY, next);
  notify();
}

/** Open the chat on an agent's thread (or Argus' own with null). */
export function openAgentChat(agent: AgentRole | null) {
  request = { agent, seq: (request?.seq ?? 0) + 1 };
  open = true;
  writeFlag(OPEN_KEY, true);
  notify();
}

export function useAskOpen(): boolean {
  return useSyncExternalStore(subscribe, () => open, () => false);
}

export function useAgentRequest(): { agent: AgentRole | null; seq: number } | null {
  return useSyncExternalStore(subscribe, () => request, () => null);
}
