import { useState } from "react";
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";

export function AutonomyLegend({ view, graph }: { view: RunView; graph: Graph }) {
  const [open, setOpen] = useState(false);
  const incidents = Object.values(view.incidents);
  const verdicts = incidents.filter((i) => i.verdict !== "UNEXPLAINED").length;
  const closed = incidents.filter((i) => i.state === "resolved").length;
  const held = view.notes.filter((n) => n.kind !== "suppressed" || !n.reason.includes("symptom")).length;
  const silenced = view.notes.filter((n) => n.reason.includes("symptom of")).length;
  const status = (id: string, fallback: string) => view.edges[id]?.status ?? fallback;
  const unsure = graph.edges.filter((e) => ["PROBATION", "PROPOSED"].includes(status(e.id, e.status))).length;
  return (
    <>
      <button className="btn autonomy-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        Autonomy boundary
      </button>
      {open && (
        <div className="autonomy">
          <h3>What Argus decides alone, and when it asks</h3>
          <div className="autonomy-cols">
            <div className="autonomy-col alone">
              <h4>Decides alone</h4>
              <ul>
                <li>
                  <b>{view.anomalies.length}</b> open an anomaly
                </li>
                <li>
                  <b>{verdicts}</b> reach a verdict from the checks
                </li>
                <li>
                  <b>{held}</b> file a "didn't wake you" note
                </li>
                <li>
                  <b>{silenced}</b> silence a symptom of an open incident
                </li>
                <li>
                  <b>{closed}</b> close an incident after it recovers
                </li>
                <li>
                  <b>{view.edgeChanges.length}</b> test an edge and set its status
                </li>
              </ul>
            </div>
            <div className="autonomy-col asks">
              <h4>Flags for a human</h4>
              <ul>
                <li>
                  <b>·</b> approval before a business action
                </li>
                <li>
                  <b>{unsure}</b> edges on probation or only proposed
                </li>
                <li>
                  <b>·</b> an ambiguous new metric placement
                </li>
                <li>
                  <b>·</b> the unexplained share of every change
                </li>
              </ul>
            </div>
          </div>
          <div className="autonomy-note">
            Statistics decide where to look and compute every number. The graph decides what to test next. A language model may
            propose and write, never decide.
          </div>
        </div>
      )}
    </>
  );
}
