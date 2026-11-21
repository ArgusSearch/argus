// REST and SSE client for the C5 API. All paths are relative: the API serves this page, or Vite proxies.

import { EVENT_TYPES, type ArgusEvent, type Graph, type Health, type Incident, type Receipt, type ReplayStatus, type RerunResult } from "./types";

/** A non-2xx answer; the message is the API's own `detail`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    detail: string,
  ) {
    super(detail);
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => json<Health>("/health"),
  graph: () => json<Graph>("/graph"),
  incident: (id: string) => json<Incident>(`/incidents/${encodeURIComponent(id)}`),
  report: async (id: string) => {
    const res = await fetch(`/incidents/${encodeURIComponent(id)}/report`);
    if (!res.ok) throw new Error(`${res.status}`);
    return res.text();
  },
  receipt: (id: string) => json<Receipt>(`/receipts/${encodeURIComponent(id)}`),
  rerun: (id: string) => json<RerunResult>(`/receipts/${encodeURIComponent(id)}/rerun`, { method: "POST" }),
  replay: (body: { action?: "play" | "pause" | "restart" | "end"; speed?: number }) =>
    json<ReplayStatus>("/replay", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  digest: () => json<Digest>("/digest"),
};

export interface DigestLine {
  key: string;
  label: string;
  value: string;
  detail: string;
  receipts: string[];
  tone: "neutral" | "good" | "warn" | "bad";
}

export interface Digest {
  title: string;
  since: string | null;
  until: string | null;
  lines: DigestLine[];
  markdown: string;
}

export interface StreamHeader {
  stream: string;
  mode: "replay" | "live";
}

export type ConnectionState = "connecting" | "open" | "offline";

/** How long to wait before reopening a stream the browser closed for good (it never retries those itself). */
export const RETRY_CLOSED_MS = 2000;

/** How long the stream may fail to reconnect before the page says the API is offline. */
export const OFFLINE_AFTER_MS = 4000;

/**
 * Follow `GET /events`. Events arrive in seq order, batched per animation frame. `onReset` fires when
 * the server starts a new stream (a replay restart, or a reconnect after one): drop the state, the
 * events that follow rebuild it. EventSource reconnects by itself and resumes with Last-Event-ID.
 */
export function follow(handlers: {
  onReset: (header: StreamHeader) => void;
  onEvents: (events: ArgusEvent[]) => void;
  onState: (state: ConnectionState) => void;
}): () => void {
  let source: EventSource | null = null;
  let closed = false;
  let queue: ArgusEvent[] = [];
  let frame = 0;
  let offline = false;
  let offlineTimer: ReturnType<typeof setTimeout> | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;

  const flush = () => {
    frame = 0;
    if (queue.length) {
      const batch = queue;
      queue = [];
      handlers.onEvents(batch);
    }
  };

  const open = () => {
    if (closed) return;
    if (!offline) handlers.onState("connecting");
    const es = new EventSource("/events");
    source = es;
    es.onopen = () => {
      clearTimeout(offlineTimer);
      offlineTimer = undefined;
      offline = false;
      handlers.onState("open");
    };
    // A stopped API refuses the connection and the browser keeps retrying with readyState CONNECTING,
    // so "offline" cannot wait for CLOSED: it is declared when no reconnect succeeds for a while.
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        clearTimeout(offlineTimer);
        offlineTimer = undefined;
        offline = true;
        handlers.onState("offline");
        // a non-200 answer (the dev proxy while the API is down) closes the stream for good: reopen it ourselves
        retry = setTimeout(open, RETRY_CLOSED_MS);
        return;
      }
      if (offline) return; // still down: keep the banner instead of flickering back to "connecting"
      handlers.onState("connecting");
      offlineTimer ??= setTimeout(() => {
        offlineTimer = undefined;
        if (closed) return;
        offline = true;
        handlers.onState("offline");
      }, OFFLINE_AFTER_MS);
    };
    es.addEventListener("stream", (msg) => {
      // events of the old stream still waiting for a frame are void
      queue = [];
      handlers.onReset(JSON.parse((msg as MessageEvent).data) as StreamHeader);
    });
    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (msg) => {
        queue.push(JSON.parse((msg as MessageEvent).data) as ArgusEvent);
        if (!frame) frame = requestAnimationFrame(flush);
      });
    }
  };

  open();
  return () => {
    closed = true;
    if (frame) cancelAnimationFrame(frame);
    clearTimeout(offlineTimer);
    clearTimeout(retry);
    source?.close();
  };
}
