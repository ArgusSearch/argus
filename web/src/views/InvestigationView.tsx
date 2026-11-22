// Y2 · The investigation as a story: every step with the question it answers, the prediction written before
// the query, the result, the decision and its receipts; next to it the case file (where, suspects, verdict).

import { useEffect, useMemo, useRef, useState } from "react";
import { Num, ReceiptChips } from "../components/Receipts";
import { dayLabel, hhmm, segmentLabel } from "../lib/format";
import { isRuledOut, type RunView, type StepView } from "../lib/store";
import type { Graph, Quantity } from "../lib/types";
import { investigations, nodeLabel } from "./model";
import { breadcrumb, chapters, CHAPTER_TITLE, scopeLabel, spreadOf, stepQuestion, suspects, verdictOf } from "./investigation";

interface Props {
  graph: Graph | null;
  view: RunView;
  onSelectNode: (id: string) => void;
  onOpenIncident: (id: string) => void;
}

const VERDICT_TEXT: Record<string, string> = {
  SUPPORTED_CAUSE: "Supported cause",
  HYPOTHESIS: "Hypothesis",
  EXPECTED: "Expected",
  DATA_ISSUE: "Data issue",
  UNEXPLAINED: "Unexplained",
};

function quantityFor(graph: Graph | null, node: string, value: number, receipt: string | null): Quantity {
  const unit = graph?.nodes.find((n) => n.id === node)?.unit ?? "";
  const mapped = unit === "share" ? "share" : unit === "eur" || unit === "eur_per_unit" ? "eur" : unit === "count" ? "count" : "";
  return { value, unit: mapped, receipt };
}

function StepCard({ s, latest }: { s: StepView; latest: boolean }) {
  const { step } = s;
  const refuted = isRuledOut(step.decision);
  const kept = step.kind === "holdout" && !refuted;
  return (
    <article className={`iv-step${latest ? " latest" : ""}${refuted ? " refuted" : ""}${kept ? " kept" : ""}`}>
      <div className="iv-step-rail" aria-hidden>
        <span className="iv-dot">{step.step}</span>
      </div>
      <div className="iv-step-body">
        <div className="iv-step-head">
          <h4>{stepQuestion(step)}</h4>
          <span className="iv-tool mono" title="the C6 tool the investigator called">
            {step.tool}
          </span>
          <span className="iv-time mono">{hhmm(s.simTs)}</span>
        </div>
        {step.hypothesis && (
          <div className="iv-hyp">
            <label>Suspect</label>
            <span className={refuted ? "struck" : undefined}>{step.hypothesis}</span>
          </div>
        )}
        {step.prediction && (
          <div className="iv-pred">
            <label>Prediction, written before the query</label>
            <span>{step.prediction}</span>
          </div>
        )}
        <div className="iv-result">{step.kind === "verdict" ? (VERDICT_TEXT[step.result] ?? step.result) : step.result}</div>
        <div className={`iv-decision${refuted ? " refuted" : kept ? " kept" : ""}`}>
          <span className="iv-mark" aria-hidden>
            {refuted ? "✗" : kept ? "✓" : "→"}
          </span>
          <span>
            {step.decision}
            {step.why && <span className="muted"> · {step.why}</span>}
          </span>
        </div>
        {step.receipts.length > 0 && (
          <div className="iv-receipts">
            <ReceiptChips ids={step.receipts} max={6} />
          </div>
        )}
      </div>
    </article>
  );
}

export function InvestigationView({ graph, view, onSelectNode, onOpenIncident }: Props) {
  const list = investigations(view);
  const [picked, setPicked] = useState<string | null>(null);
  const current = list.find((i) => i.anomalyId === picked) ?? list[list.length - 1] ?? null;
  const steps = useMemo(() => (current ? view.steps.filter((s) => s.anomalyId === current.anomalyId) : []), [view.steps, current]);
  const anomaly = current ? view.anomalies.find((a) => a.id === current.anomalyId) : undefined;
  const incident = current?.incidentId ? view.incidents[current.incidentId] : undefined;
  const skeptic = current?.incidentId ? view.skeptic.filter((k) => k.incident_id === current.incidentId) : [];
  const trail = steps.map((s) => s.step);
  const crumbs = breadcrumb(trail, anomaly?.node ?? null);
  const suspectList = suspects(steps);
  // no segment path: the change is spread over the scope of the cause that was kept (S4: country DE, FR)
  const spread = spreadOf(suspectList);
  const verdict = verdictOf(trail);
  const latestSeq = steps.length ? steps[steps.length - 1].seq : -1;
  const end = useRef<HTMLDivElement>(null);
  const following = picked === null;
  // the newest step already shown; null until the first steps arrive (the page catches up on the run when it loads)
  const seenSeq = useRef<number | null>(null);

  // a running investigation keeps its newest step in view; one that is already decided when its steps first
  // arrive opens at its first chapter, so the story reads from the start
  useEffect(() => {
    if (latestSeq < 0 || latestSeq === seenSeq.current) return;
    const firstLook = seenSeq.current === null;
    seenSeq.current = latestSeq;
    if (firstLook && verdict) return;
    if (following) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [latestSeq, following, verdict]);

  if (!current || !anomaly) {
    return (
      <section className="vw iv" aria-label="investigation">
        <div className="vw-empty">
          <div className="vw-empty-title">No investigation yet</div>
          Argus scores the ★ metrics against the same hour of the last four weeks, every hour. The first anomaly opens an investigation here by
          itself, with no one asking.
        </div>
      </section>
    );
  }

  const groups = chapters(steps);
  const verdictCard = (
    <div className={`iv-card verdict${verdict ? ` v-${incident?.verdict ?? verdict}` : ""}`}>
      <div className="iv-card-label">Verdict</div>
      {verdict ? (
        <>
          <div className="iv-verdict">{VERDICT_TEXT[incident?.verdict ?? verdict] ?? verdict}</div>
          {incident && (
            <>
              <div className="iv-meta">
                {incident.title} · {incident.state}
              </div>
              <button className="btn primary" onClick={() => onOpenIncident(incident.id)}>
                Open the report · {incident.id}
              </button>
            </>
          )}
        </>
      ) : (
        <div className="muted">Not decided yet. Argus stops when the evidence explains at least 80% of the change.</div>
      )}
    </div>
  );
  return (
    <section className="vw iv" aria-label="investigation">
      <div className="vw-bar">
        <div>
          <h2 className="vw-title">
            Investigation <span className="mono muted">{current.anomalyId}</span>
          </h2>
          <p className="vw-sub">
            A fixed playbook, then the suspects. Every prediction is written down before its query runs; every number opens its SQL.
          </p>
        </div>
        <span className="tv-fill" />
        {list.length > 1 && (
          <div className="iv-picker" role="tablist" aria-label="investigations">
            {list.map((i) => (
              <button
                key={i.anomalyId}
                role="tab"
                aria-selected={i.anomalyId === current.anomalyId}
                className={`chip-btn${i.anomalyId === current.anomalyId ? " on" : ""}`}
                onClick={() => setPicked(i.anomalyId === list[list.length - 1].anomalyId ? null : i.anomalyId)}
              >
                {i.incidentId ?? i.anomalyId} · {nodeLabel(graph, i.node)}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="iv-grid">
        <div className="vw-scroll iv-story">
          {groups.map((g, i) => (
            <div key={`${g.chapter}-${i}`} className={`iv-chapter c-${g.chapter}`}>
              <div className="iv-chapter-title">{CHAPTER_TITLE[g.chapter]}</div>
              {g.steps.map((s) => (
                <StepCard key={s.seq} s={s} latest={s.seq === latestSeq && !verdict} />
              ))}
            </div>
          ))}
          {skeptic.length > 0 && (
            <div className="iv-chapter c-skeptic">
              <div className="iv-chapter-title">7 · Try to break it</div>
              {skeptic.map((k) => (
                <article key={k.seq} className="iv-step skeptic">
                  <div className="iv-step-rail" aria-hidden>
                    <span className="iv-dot">S</span>
                  </div>
                  <div className="iv-step-body">
                    <div className="iv-step-head">
                      <h4>{k.check}</h4>
                    </div>
                    <div className="iv-result">{k.result}</div>
                    <ReceiptChips ids={k.receipts} max={6} />
                  </div>
                </article>
              ))}
            </div>
          )}
          {!verdict && (
            <div className="iv-working" role="status">
              <span className="iv-spinner" aria-hidden />
              Working on the next check…
            </div>
          )}
          <div ref={end} />
        </div>

        <aside className="vw-scroll iv-case" aria-label="case file">
          {verdict && verdictCard}
          <div className="iv-card">
            <div className="iv-card-label">What tripped</div>
            <button className="iv-node tv-link" onClick={() => onSelectNode(anomaly.node)}>
              {nodeLabel(graph, anomaly.node)}
            </button>
            <div className="iv-facts">
              <div>
                <label>observed</label>
                <Num q={quantityFor(graph, anomaly.node, anomaly.observed, anomaly.receipts[0] ?? null)} />
              </div>
              <div>
                <label>expected</label>
                <Num q={quantityFor(graph, anomaly.node, anomaly.expected, anomaly.receipts[0] ?? null)} />
              </div>
              <div>
                <label>score</label>
                <Num q={{ value: anomaly.z, unit: "z", receipt: anomaly.receipts[0] ?? null }} />
              </div>
            </div>
            <div className="iv-meta">
              {anomaly.direction === "down" ? "Drop" : "Spike"} in {segmentLabel(anomaly.segment)} · data hour {dayLabel(anomaly.hour)} {hhmm(anomaly.hour)} ·
              opened {hhmm(anomaly.detected_at)}
            </div>
          </div>

          <div className="iv-card">
            <div className="iv-card-label">Where it is</div>
            {crumbs.crumbs.length ? (
              <nav className="iv-crumbs" aria-label="root-cause path">
                <button className="iv-crumb node" onClick={() => onSelectNode(anomaly.node)}>
                  {anomaly.node}
                </button>
                {crumbs.crumbs.map((c) => (
                  <span key={`${c.dim}-${c.value}`} className="iv-crumb-wrap">
                    <span className="iv-sep" aria-hidden>
                      ›
                    </span>
                    <span className="iv-crumb">
                      <i>{c.dim}</i>
                      {c.value}
                    </span>
                  </span>
                ))}
              </nav>
            ) : spread ? (
              <div className="iv-spread">
                No single segment carries it. It sits where <b>{spread.description}</b> applied:{" "}
                <span className="iv-crumb">{scopeLabel(spread.scope)}</span>
              </div>
            ) : (
              <div className="muted">{steps.some((s) => s.step.kind === "segment") ? "No single segment carries it." : "The segment search has not run yet."}</div>
            )}
          </div>

          <div className="iv-card">
            <div className="iv-card-label">
              Suspects <span className="muted">· {suspectList.length ? `${suspectList.filter((s) => !s.kept).length} ruled out` : "none tested yet"}</span>
            </div>
            {suspectList.map((s) => (
              <div key={s.seq} className={`iv-suspect${s.kept ? " kept" : " out"}`}>
                <div className="iv-suspect-head">
                  <span className="iv-suspect-mark" aria-hidden>
                    {s.kept ? "✓" : "✗"}
                  </span>
                  <span className={`iv-suspect-name${s.kept ? "" : " struck"}`}>{s.description}</span>
                </div>
                <div className="iv-suspect-meta mono">
                  {s.log} · {s.ref} · {hhmm(s.ts)} · scope {scopeLabel(s.scope)}
                </div>
                <div className="iv-suspect-why">
                  <b>{s.kept ? "Kept" : "Ruled out"}:</b> {s.reason}
                  <ReceiptChips ids={s.receipts} max={3} />
                </div>
              </div>
            ))}
          </div>

          {!verdict && verdictCard}
        </aside>
      </div>
    </section>
  );
}
