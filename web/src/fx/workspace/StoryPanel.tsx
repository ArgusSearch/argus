// The visualization's side panel: what the map is for, in one sentence, and the latest incident's story played
// on it. Each step lights on the map as it lights here (the scene follows the story's focus), the money lands
// on the block it was lost at, and the suspects that were ruled out are struck through.

import { useEffect, useMemo, useState } from "react";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { openIncidentPage } from "../nav";
import { STATE } from "./plain";
import { setStoryFocus, storyFocus, storyOf, type Story } from "./story";
import { Pill, useIncidents } from "./ui";

const STEP_MS = 1500;

export function StoryPanel({ graph, view }: { graph: Graph | null; view: RunView }) {
  const { incidents } = useIncidents(view);
  const incident = useMemo(() => [...incidents].sort((a, b) => b.opened_at.localeCompare(a.opened_at))[0] ?? null, [incidents]);
  const story: Story | null = useMemo(() => (graph && incident ? storyOf(graph, incident) : null), [graph, incident]);
  const [at, setAt] = useState(-1);
  const [run, setRun] = useState(0);
  // a live investigation owns the map: the story waits until the walk has its verdict
  const busy = view.focus !== null && view.steps.length > 0 && !view.steps.some((s) => s.step.kind === "verdict" && s.anomalyId === view.anomalies[view.anomalies.length - 1]?.id);

  useEffect(() => {
    if (!story || busy) {
      setStoryFocus(null);
      setAt(-1);
      return;
    }
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setAt(story.steps.length - 1);
      setStoryFocus(storyFocus(story, story.steps.length - 1));
      return;
    }
    let i = -1;
    setAt(-1);
    setStoryFocus(null);
    const timers: number[] = [];
    const next = () => {
      i += 1;
      setAt(i);
      // the current step leads; the chain so far stays lit behind it
      setStoryFocus(storyFocus(story, i));
      if (i < story.steps.length - 1) timers.push(window.setTimeout(next, STEP_MS));
    };
    timers.push(window.setTimeout(next, 900));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [story, busy, run]);

  // leaving the visualization hands the map back to the run
  useEffect(() => () => setStoryFocus(null), []);
  // while the story plays, the investigation's own step numbers step aside on the map
  const playing = at >= 0;
  useEffect(() => {
    document.documentElement.toggleAttribute("data-fx-story", playing);
    return () => document.documentElement.removeAttribute("data-fx-story");
  }, [playing]);

  return (
    <aside className="ws-story" aria-label="what the map shows">
      <section className="ws-story-card">
        <h2>How to read it</h2>
        <ul className="ws-story-legend">
          <li>
            <i className="big" /> the main chain: visitors, conversion, orders, revenue, and the ad side
          </li>
          <li>
            <i className="small" /> detail metrics, small until you point at one
          </li>
          <li>
            <i className="line" /> a line means one number is built from another
          </li>
          <li>
            <i className="log" /> change logs: releases, provider status, plans
          </li>
        </ul>
      </section>
      <section className="ws-story-card">
        <header className="ws-story-head">
          <h2>Follow an incident</h2>
          {story && (
            <button className="btn" onClick={() => setRun((r) => r + 1)} disabled={busy}>
              Review investigation
            </button>
          )}
        </header>
        {!story && <p className="fx-empty">No incident yet. When one happens, its path through the map lights up here.</p>}
        {story && incident && (
          <>
            <p className="ws-story-id">
              <span className="mono">{incident.id}</span>
              <Pill tone={STATE[incident.state].tone}>{STATE[incident.state].label}</Pill>
            </p>
            {busy && <p className="ws-story-busy">An investigation is running: the map is showing it live.</p>}
            <ol className="ws-story-steps">
              {story.steps.map((s, i) => (
                <li key={s.key} className={`k-${s.kind}${i <= at ? " lit" : ""}${i === at ? " now" : ""}`}>
                  <i aria-hidden="true">{s.kind === "ruled" ? "✕" : s.kind === "cause" ? "✓" : ""}</i>
                  <span>
                    {s.kind === "ruled" && <em>Ruled out: </em>}
                    {s.text}
                  </span>
                  {s.value && <b>{s.value}</b>}
                </li>
              ))}
            </ol>
            <button className="btn primary" onClick={() => openIncidentPage(incident.id)}>
              Read the full story
            </button>
          </>
        )}
      </section>
    </aside>
  );
}
