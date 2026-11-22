// Small building blocks shared by the workspace's pages: the card frame, status pills, a glossary term with its
// tooltip, the mini chart of the KPI tiles, and the hook that keeps the full incidents (with findings) current.

import { useEffect, useState, type ReactNode } from "react";
import { analysisWindow, visibleFindings } from "../../analysis/pages/model";
import { useAgentDemo } from "../../lib/agentDemo";
import { api } from "../../lib/api";
import type { RunView } from "../../lib/store";
import type { Incident } from "../../lib/types";
import { gloss, type Tone } from "./plain";

export function Card({
  title,
  action,
  className,
  children,
  term,
  light,
}: {
  title: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
  term?: string;
  /** the glass catches the pointer's light (usePointerLight on the page) */
  light?: boolean;
}) {
  return (
    <section className={`fx-card${className ? ` ${className}` : ""}`} data-light={light ? "" : undefined}>
      <header className="fx-card-head">
        <h2 className="fx-hud">{term ? <Term term={term}>{title}</Term> : title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

export function Pill({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`ws-pill t-${tone}`} title={title}>
      {children}
    </span>
  );
}

/**
 * A word with a glossary tooltip: hover or focus shows the plain meaning of the internal term behind it. The
 * label stays plain; the term itself only appears inside the tooltip.
 */
export function Term({ term, children }: { term: string; children?: ReactNode }) {
  const entry = gloss(term);
  if (!entry) return <>{children ?? term}</>;
  return (
    <span className="ws-term" tabIndex={0}>
      {children ?? entry.plain}
      <span className="ws-tip" role="tooltip">
        <b>{entry.plain}</b>
        {entry.term !== entry.plain && <i>{entry.term}</i>}
        <span>{entry.meaning}</span>
      </span>
    </span>
  );
}

/** A mini area chart of one value per hour, scaled to its own range (0 at the bottom). */
export function Spark({ values, className }: { values: number[]; className?: string }) {
  const w = 200;
  const h = 44;
  // a little headroom, so a series that sits at its maximum (a flat line) reads as a line, not a filled block
  const top = Math.max(...values, 1e-9) * 1.25;
  const y = (v: number) => h - 2 - (v / top) * (h - 6);
  const x = (i: number) => (values.length < 2 ? 0 : (i * w) / (values.length - 1));
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  return (
    <svg className={`ws-spark${className ? ` ${className}` : ""}`} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      {values.length > 1 && (
        <>
          <path className="ws-spark-area" d={`${line}L${w},${h}L0,${h}Z`} />
          <path className="ws-spark-line" d={line} pathLength={1} />
        </>
      )}
    </svg>
  );
}

/**
 * The incidents of the run with their findings (GET /incidents), re-read whenever an incident changes on the
 * stream, so the tasks and the incident list follow the run.
 */
export function useIncidents(view: RunView): { incidents: Incident[]; failed: boolean } {
  const demo = useAgentDemo();
  const [state, setState] = useState<{ incidents: Incident[]; failed: boolean }>({ incidents: [], failed: false });
  const version = Object.values(view.incidents)
    .map((i) => `${i.id}:${i.lastSeq}`)
    .join(",");
  useEffect(() => {
    if (demo) return;
    let live = true;
    if (!version) {
      setState({ incidents: [], failed: false });
      return;
    }
    api.incidents().then(
      (incidents) => live && setState({ incidents, failed: false }),
      () => live && setState((s) => ({ ...s, failed: true })),
    );
    return () => {
      live = false;
    };
  }, [version, view.stream, demo?.runId]);
  // the agent presentation carries its incidents in its snapshot
  if (demo) return { incidents: demo.snapshot?.incidents ?? [], failed: false };
  const window = analysisWindow(view.simTs, "all");
  return { ...state, incidents: state.incidents.filter((incident) => visibleFindings(incident, view.incidents[incident.id], window)) };
}

/** One incident with its findings, re-read whenever it changes on the stream. */
export function useIncident(id: string, version: number, stream: string | null): { incident: Incident | null; error: string | null } {
  const demo = useAgentDemo();
  const [state, setState] = useState<{ incident: Incident | null; error: string | null }>({ incident: null, error: null });
  useEffect(() => {
    if (demo) return;
    let live = true;
    api.incident(id).then(
      (incident) => live && setState({ incident, error: null }),
      (e: Error) => live && setState({ incident: null, error: e.message }),
    );
    return () => {
      live = false;
    };
  }, [id, version, stream, demo?.runId]);
  if (demo) {
    const found = demo.snapshot?.incidents.find((i) => i.id === id) ?? null;
    return { incident: found, error: demo.error ?? (demo.snapshot && !found ? "This incident is not in the presentation yet." : null) };
  }
  return state;
}
