// "While you slept" (GET /digest) and the autonomy boundary legend.

import { useEffect, useState } from "react";
import { api, type Digest } from "../lib/api";
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { ReceiptChips } from "./Receipts";
import { ErrorState, Skeleton } from "../ui";

export function DigestModal({ version, onClose }: { version: number; onClose: () => void }) {
  const [digest, setDigest] = useState<Digest | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setError(null);
    api.digest().then(
      (d) => live && setDigest(d),
      (e: unknown) => live && setError(e),
    );
    return () => {
      live = false;
    };
  }, [version, attempt]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal digest" role="dialog" aria-label="While you slept">
        <div className="modal-head">
          <div style={{ flex: 1 }}>
            <h2>{digest?.title ?? "While you slept"}</h2>
            <p>Everything Argus did on its own, one line each. Click a receipt to see the query behind a number.</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="modal-body">
          {digest ? (
            <div className="digest-lines">
              {digest.lines.map((line) => (
                <div key={line.key} className={`dline ${line.tone}`}>
                  <span className="dline-label">{line.label}</span>
                  <span className="dline-value">{line.value}</span>
                  <span className="dline-detail">
                    {line.detail}
                    {line.receipts.length > 0 ? (
                      <div>
                        <ReceiptChips ids={line.receipts} max={5} />
                      </div>
                    ) : (
                      <div className="muted" style={{ fontSize: 11 }}>
                        a count of what the monitor did, no query behind it
                      </div>
                    )}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            error ? <ErrorState error={error} route="/digest" onRetry={() => setAttempt((n) => n + 1)} /> : <Skeleton lines={6} label="Loading the report" />
          )}
        </div>
        <div className="modal-foot">
          <button
            className="btn"
            disabled={!digest}
            onClick={() => digest && void navigator.clipboard.writeText(digest.markdown)}
          >
            Copy as Markdown
          </button>
          <span className="verify">Counts come from the stream; money and verdicts come from receipts.</span>
        </div>
      </div>
    </>
  );
}

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
