// The live investigation: a fixed playbook, each step with its prediction, result, decision and receipts.

import { Fragment, useEffect, useRef } from "react";
import { hhmm, humanize } from "../lib/format";
import { isRuledOut, type RunView } from "../lib/store";
import { ReceiptChips } from "./Receipts";

// the fixed opening of argus.investigator.procedure, in order
const PLAYBOOK: [string, string][] = [
  ["freshness", "freshness"],
  ["identities", "identities"],
  ["calendar", "calendar"],
  ["decompose", "formula split"],
  ["segment", "segment search"],
  ["events", "events"],
  ["holdout", "holdout"],
  ["impact", "impact"],
  ["verdict", "verdict"],
];

export function Trail({ view }: { view: RunView }) {
  const anomaly = view.anomalies[view.anomalies.length - 1];
  const steps = anomaly ? view.steps.filter((s) => s.anomalyId === anomaly.id) : [];
  const skeptic = steps.length ? view.skeptic.filter((s) => s.incident_id === steps[0].incidentId) : [];
  const done = new Set(steps.map((s) => s.step.kind));
  const finished = done.has("verdict");
  const current = finished ? null : (steps[steps.length - 1]?.step.kind ?? (anomaly ? "freshness" : null));
  const scroller = useRef<HTMLDivElement>(null);
  const total = steps.length + skeptic.length;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [total]);

  const latestSeq = Math.max(0, ...steps.map((s) => s.seq), ...skeptic.map((s) => s.seq));

  return (
    <section className="trail" aria-label="investigation trail">
      <div className="trail-head">
        <span className="panel-title">Investigation</span>
        {anomaly ? (
          <span className="playbook">
            <span className="muted" style={{ marginRight: 4 }}>
              {anomaly.direction === "down" ? "Drop" : "Spike"} playbook
            </span>
            {PLAYBOOK.map(([kind, label]) => (
              <span key={kind} className={`pb-step${done.has(kind) && kind !== current ? " done" : ""}${kind === current ? " now" : ""}`}>
                {label}
              </span>
            ))}
            {skeptic.length > 0 && <span className="pb-step done">skeptic</span>}
          </span>
        ) : (
          <span className="muted">no anomaly yet: the watcher scores the ★ metrics every hour</span>
        )}
      </div>
      {total ? (
        <div className="trail-steps" ref={scroller}>
          {steps.map(({ seq, step }) => {
            const refuted = isRuledOut(step.decision);
            return (
              <article key={seq} className={`tstep${seq === latestSeq ? " latest" : ""}`}>
                <div className="tstep-head">
                  <span className="tstep-n">{step.step}</span>
                  <span className="tstep-kind">{humanize(step.kind)}</span>
                  <span className="mono" style={{ marginLeft: "auto" }}>
                    {step.tool}
                  </span>
                </div>
                {step.prediction && <div className="tstep-pred">Predicts: {step.prediction}</div>}
                <div className="tstep-result">{step.result}</div>
                <div className={`tstep-decision${refuted ? " refuted" : ""}`}>
                  <span>{refuted ? "✗" : "→"}</span>
                  <span>{step.decision}</span>
                </div>
                <ReceiptChips ids={step.receipts} />
              </article>
            );
          })}
          {skeptic.map((s) => (
            <article key={s.seq} className={`tstep skeptic${s.seq === latestSeq ? " latest" : ""}`}>
              <div className="tstep-head">
                <span className="tstep-n">S</span>
                <span className="tstep-kind">Skeptic</span>
                <span className="mono" style={{ marginLeft: "auto" }}>
                  refute
                </span>
              </div>
              <div className="tstep-pred">{s.check}</div>
              <div className="tstep-result">{s.result}</div>
              <ReceiptChips ids={s.receipts} />
            </article>
          ))}
        </div>
      ) : anomaly ? (
        <div className="trail-empty">Opening the investigation…</div>
      ) : (
        <Watchlist view={view} />
      )}
    </section>
  );
}

/** Quiet hours: the metrics closest to the alarm line this hour, so the watching is visible. */
function Watchlist({ view }: { view: RunView }) {
  const z = view.tick?.max_abs_z ?? {};
  const top = Object.entries(z)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6);
  if (!top.length) return <div className="trail-empty">Waiting for the first tick…</div>;
  const alarm = view.thresholds.alarm_z;
  const scale = alarm * 1.25;
  return (
    <div className="trail-steps">
      <article className="tstep watch-intro">
        <div className="tstep-head">
          <span className="tstep-kind">Quiet hour {hhmm(view.tick?.hour)}</span>
        </div>
        <div className="tstep-result">
          The ★ metrics are scored against the same hour of the last four weeks. Nothing crossed the alarm line, so nobody gets
          paged.
        </div>
        <div className="tstep-pred">Closest to the line right now →</div>
      </article>
      {top.map(([node, value]) => (
        <article key={node} className="tstep watch">
          <div className="tstep-head">
            <span className="tstep-kind mono watch-node" title={node}>
              {node.split("_").map((part, i) => (
                <Fragment key={i}>
                  {i > 0 && (
                    <>
                      _<wbr />
                    </>
                  )}
                  {part}
                </Fragment>
              ))}
            </span>
          </div>
          <div className="watch-z">
            <b>{value.toFixed(1)}</b>
            <span>alarm line {alarm}</span>
          </div>
          <div className="gauge-bar">
            <span className="gauge-fill" style={{ width: `${Math.min(value / scale, 1) * 100}%`, opacity: value >= view.thresholds.wiggle_z ? 0.9 : 0.4 }} />
            <span className="gauge-line" style={{ left: `${(alarm / scale) * 100}%` }} />
          </div>
        </article>
      ))}
    </div>
  );
}
