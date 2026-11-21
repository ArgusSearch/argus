// REST and SSE client for the C5 API. All paths are relative: the API serves this page, or Vite proxies.

import { EVENT_TYPES, type ArgusEvent, type Graph, type Health, type Incident, type Receipt, type ReplayStatus, type RerunResult } from "./types";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status} ${detail}`);
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

/**
 * Follow `GET /events`. `onReset` fires for every new stream (first connect, replay restart);
 * the caller drops its state. Events arrive in seq order.
 */
export function follow(handlers: {
  onReset: (header: StreamHeader) => void;
  onEvents: (events: ArgusEvent[]) => void;
  onState: (state: ConnectionState) => void;
}): () => void {
  let source: EventSource | null = null;
  let stream: string | null = null;
  let closed = false;
  let queue: ArgusEvent[] = [];
  let frame = 0;

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
    handlers.onState("connecting");
    const es = new EventSource("/events");
    source = es;
    es.onopen = () => handlers.onState("open");
    es.onerror = () => handlers.onState(es.readyState === EventSource.CLOSED ? "offline" : "connecting");
    es.addEventListener("stream", (msg) => {
      const header = JSON.parse((msg as MessageEvent).data) as StreamHeader;
      handlers.onState("open");
      if (stream !== null && header.stream !== stream) {
        // the run restarted: rebuild from the first event on a fresh connection
        stream = header.stream;
        queue = [];
        handlers.onReset(header);
        es.close();
        open();
        return;
      }
      if (stream === null) handlers.onReset(header);
      stream = header.stream;
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
    source?.close();
  };
}
