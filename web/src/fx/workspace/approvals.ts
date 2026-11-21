// Approvals of proposed actions. Argus never acts on the business by itself: a proposed action waits for a person,
// and approving it hands it to the team. There is no approval route in the API yet (POST /incidents/{id}/feedback
// is a stub), so the approval is kept in this browser, per stream, and the page says so.

import { useSyncExternalStore } from "react";

const KEY = "argus.approvals.v1";

function read(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

let approved: Record<string, string> = typeof window === "undefined" ? {} : read();
const listeners = new Set<() => void>();

const keyOf = (stream: string | null, incident: string) => `${stream ?? "-"}:${incident}`;

/** Records the approval (the simulated time it was given) and tells every subscriber. */
export function approve(stream: string | null, incident: string, at: string) {
  approved = { ...approved, [keyOf(stream, incident)]: at };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(approved));
  } catch {
    /* private mode: the approval holds for this page load */
  }
  for (const l of [...listeners]) l();
}

/** The simulated time the action of this incident was approved, or null. */
export function useApproval(stream: string | null, incident: string): string | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => approved[keyOf(stream, incident)] ?? null,
    () => null,
  );
}
