// Y3 · Demo mode: the page plays the run by itself for the video. It restarts the replay at the chosen speed,
// switches to the investigation when the first step arrives, opens the incident when it has a verdict,
// returns to the graph after `hold` seconds, and (with captions) shows one line per beat. Esc leaves it.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import type { RunView } from "../../lib/store";
import type { Graph, Health } from "../../lib/types";
import { beatFor, decidedIncidents, demoOptions, investigationStarted, withoutDemo, type Beat, type DemoOptions } from "./demo";

export type DemoTab = "graph" | "tree" | "investigation" | "report" | "scorecard";

/** How long the finished walk stays on screen before the report opens over it. */
const REPORT_DELAY_MS = 3500;

interface Args {
  view: RunView;
  graph: Graph | null;
  health: Health | null;
  setTab: (tab: DemoTab) => void;
  onOpenIncident: (id: string) => void;
}

export function useDemo({ view, graph, health, setTab, onOpenIncident }: Args): { options: DemoOptions; beat: Beat | null } {
  const [options, setOptions] = useState<DemoOptions>(() => demoOptions(window.location.search));
  // the stream that was on screen when demo mode restarted the replay; its events are not followed
  const started = useRef<{ before: string | null } | null>(null);
  const timers = useRef<number[]>([]);
  const synthetic = useRef(false);
  const seen = useRef({ stream: null as string | null, investigating: false, opened: new Set<string>(), ended: false });

  const clearTimers = useCallback(() => {
    for (const t of timers.current) window.clearTimeout(t);
    timers.current = [];
  }, []);
  const later = useCallback((ms: number, fn: () => void) => {
    timers.current.push(window.setTimeout(fn, ms));
  }, []);
  /** Close whatever sheet is open: the sheets close on Escape, which must not also end demo mode. */
  const closeSheets = useCallback(() => {
    synthetic.current = true;
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    synthetic.current = false;
  }, []);

  // the page's look for the video
  useEffect(() => {
    if (!options.demo) return;
    const root = document.documentElement;
    root.classList.add("argus-demo");
    return () => root.classList.remove("argus-demo");
  }, [options.demo]);

  // Esc leaves demo mode and drops its options from the address bar
  useEffect(() => {
    if (!options.demo) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || synthetic.current) return;
      clearTimers();
      setOptions((o) => ({ ...o, demo: false }));
      window.history.replaceState(null, "", withoutDemo(window.location.href));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [options.demo, clearTimers]);

  // start once the API says what it is: a replay restarts from the first tick, a live run keeps going.
  // The stream id comes from /health: a page that joined the first stream never gets a stream header.
  const mode = health?.mode;
  const stream = health?.stream ?? null;
  useEffect(() => {
    if (!options.demo || started.current || !mode || (mode === "replay" && !stream)) return;
    started.current = { before: mode === "replay" ? stream : null };
    setTab("graph");
    const body = mode === "replay" ? ({ action: "restart", speed: options.speed } as const) : ({ action: "play", speed: options.speed } as const);
    void api.replay(body).catch(() => undefined);
  }, [options.demo, options.speed, mode, stream, setTab]);

  // a new stream (the restart, or a reconnect after one) starts the choreography over
  useEffect(() => {
    if (seen.current.stream === view.stream) return;
    seen.current = { stream: view.stream, investigating: false, opened: new Set(), ended: false };
    clearTimers();
  }, [view.stream, clearTimers]);

  // follow the run
  const finished = Boolean(health?.run.finished && view.lastSeq >= (health?.last_seq ?? Infinity));
  useEffect(() => {
    const start = started.current;
    // a replay is followed from its restart on: the page knows it by the new stream's header
    if (!options.demo || !start || (start.before !== null && (view.stream === null || view.stream === start.before))) return;
    const s = seen.current;
    if (!s.investigating && investigationStarted(view)) {
      s.investigating = true;
      setTab("investigation");
    }
    for (const id of decidedIncidents(view)) {
      if (s.opened.has(id)) continue;
      s.opened.add(id);
      later(REPORT_DELAY_MS, () => onOpenIncident(id));
      later(REPORT_DELAY_MS + options.hold * 1000, () => {
        closeSheets();
        setTab("graph");
      });
    }
    if (options.endOnReport && finished && !s.ended) {
      s.ended = true;
      const after = s.opened.size ? REPORT_DELAY_MS + options.hold * 1000 + 1500 : 1500;
      later(after, () => {
        closeSheets();
        setTab("report");
      });
    }
  }, [options.demo, options.hold, options.endOnReport, view, finished, setTab, onOpenIncident, later, closeSheets]);

  useEffect(() => clearTimers, [clearTimers]);

  return { options, beat: options.demo && options.captions ? beatFor(view, graph) : null };
}

export function CaptionStrip({ beat }: { beat: Beat }) {
  return (
    <div className="cap" role="status" aria-live="polite">
      <span key={beat.text} className={`cap-line b-${beat.id}`}>
        {beat.text}
      </span>
    </div>
  );
}
