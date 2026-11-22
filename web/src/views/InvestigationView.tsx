// Y2 · The investigation as a story: every step with the question it answers, the prediction written before
// the query, the result, the decision and its receipts; next to it the case file (where, suspects, verdict).

import { useEffect, useMemo, useRef, useState } from "react";
import { AgentReceiptChips, Num, ReceiptChips } from "../components/Receipts";
import { useAgent } from "../fx/workspace/agent";
import { useAppState } from "../lib/AppState";
import type { ActivityRecord } from "../lib/agent";
import { dayLabel, hhmm, humanize, monitoringText, segmentLabel } from "../lib/format";
import { isRuledOut, type RunView, type StepView } from "../lib/store";
import type { Graph, Quantity } from "../lib/types";
import { nodeLabel } from "./model";
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
          <span className="iv-tool mono">
            {humanize(step.tool)}
          </span>
          <span className="iv-time mono">{hhmm(s.simTs)}</span>
        </div>
        {step.hypothesis && (
          <div className="iv-hyp">
            <label>Suspect</label>
            <span className={refuted ? "struck" : undefined}>{monitoringText(step.hypothesis)}</span>
          </div>
        )}
        {step.prediction && (
          <div className="iv-pred">
            <label>Prediction, written before the query</label>
            <span>{monitoringText(step.prediction)}</span>
          </div>
        )}
        <div className="iv-result">{monitoringText(step.kind === "verdict" ? (VERDICT_TEXT[step.result] ?? step.result) : step.result)}</div>
        <div className={`iv-decision${refuted ? " refuted" : kept ? " kept" : ""}`}>
          <span className="iv-mark" aria-hidden>
            {refuted ? "✗" : kept ? "✓" : "→"}
          </span>
          <span>
            {monitoringText(step.decision)}
            {step.why && <span className="muted"> · {monitoringText(step.why)}</span>}
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

function AgentChecks({ records }: { records: ActivityRecord[] }) {
  if (!records.length) return null;
  return (
    <div className="iv-chapter">
      <div className="iv-chapter-title">Agent checks</div>
      {records.map((record) => (
        <article className="iv-step" key={record.seq}>
          <div className="iv-step-body">
            <div className="iv-step-head">
              <h4>{record.tool ? humanize(record.tool) : "Investigation update"}</h4>
              <span className="iv-time mono">{hhmm(record.sim_ts)}</span>
            </div>
            <div className="iv-result">{monitoringText(record.observation?.summary || record.text)}</div>
            <AgentReceiptChips links={record.receipt_links.length ? record.receipt_links : record.observation?.receipt_refs ?? []} />
          </div>
        </article>
      ))}
    </div>
  );
}

export function InvestigationView({ graph, view, onSelectNode, onOpenIncident }: Props) {
  const { monitor } = useAppState();
  const agent = useAgent();
  const [picked, setPicked] = useState<string | null>(null);
  const currentId = monitor.investigating?.id ?? monitor.runningInvestigation?.anomaly_id;
  const start = currentId ? view.anomalies.find((a) => a.id === currentId) : undefined;
  const list = start && !monitor.cases.some((item) => item.anomalyId === start.id)
    ? [...monitor.cases, { anomalyId: start.id, node: start.node, incidentId: monitor.runningInvestigation?.incident_id ?? null, steps: 0 }]
    : monitor.cases;
  const defaultCase = list.find((i) => i.anomalyId === currentId) ?? list.at(-1);
  const current = list.find((i) => i.anomalyId === picked) ?? defaultCase;
  const steps = useMemo(() => (current ? view.steps.filter((s) => s.anomalyId === current.anomalyId) : []), [view.steps, current?.anomalyId]);
  const relevantRun = current
    ? agent.runs.findLast((run) => run.kind === "investigate" && (run.anomaly_id === current.anomalyId
      || (current.incidentId && run.incident_id === current.incidentId)))
    : monitor.runningInvestigation;
  const records = relevantRun
    ? agent.records.filter((r) => r.run_id === relevantRun.run_id && (r.kind === "tool_call" || r.kind === "tool_result" || r.kind === "report"))
    : [];
  const working = current ? current.anomalyId === currentId : monitor.activeInvestigation;
  const anomaly = current ? view.anomalies.find((a) => a.id === current.anomalyId) : undefined;
  const incident = current?.incidentId ? view.incidents[current.incidentId] : undefined;
  const skeptic = current?.incidentId ? view.skeptic.filter((k) => k.incident_id === current.incidentId) : [];
  const trail = steps.map((s) => s.step);
  const crumbs = breadcrumb(trail, anomaly?.node ?? null);
  const suspectList = suspects(steps);
  // no segment path: the change is spread over the scope of the cause that was kept (S4: country DE, FR)
  const spread = spreadOf(suspectList);
  const verdict = verdictOf(trail);
  const latestSeq = steps.at(-1)?.seq;
  const latestAgentSeq = records.at(-1)?.seq;
  const end = useRef<HTMLDivElement>(null);
  const following = picked === null;

  // a running investigation keeps its newest step in view
  useEffect(() => {
    if (following) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [latestSeq, latestAgentSeq, following]);

  if (!current || !anomaly) {
    return (
      <section className="vw iv" aria-label="investigation">
        <div className="vw-empty">
          <div className="vw-empty-title">{working ? "Investigating a metric change" : "No investigation yet"}</div>
          {working ? "Argus is checking what changed." : "Argus checks your key metrics every hour. Investigations appear here when a metric moves outside its usual range."}
        </div>
        <AgentChecks records={records} />
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
                {monitoringText(incident.title)} · {incident.state}
              </div>
              <button className="btn primary" onClick={() => onOpenIncident(incident.id)}>
                Open the incident report
              </button>
            </>
          )}
        </>
      ) : (
        <div className="muted">{working ? "Argus is still checking the evidence." : "No verdict was filed for this investigation."}</div>
      )}
    </div>
  );
  return (
    <section className="vw iv" aria-label="investigation">
      <div className="vw-bar">
        <div>
          <h2 className="vw-title">
            Investigation <span className="mono muted">{nodeLabel(graph, anomaly.node)}</span>
          </h2>
          <p className="vw-sub">
            Follow the checks, possible causes and evidence behind a metric change.
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
                onClick={() => setPicked(i.anomalyId === defaultCase?.anomalyId ? null : i.anomalyId)}
              >
                {nodeLabel(graph, i.node)} · {hhmm(view.anomalies.find((a) => a.id === i.anomalyId)?.detected_at)}
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
                <StepCard key={s.seq} s={s} latest={s.seq === latestSeq && working && !verdict} />
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
          <AgentChecks records={records} />
          {working && (
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
                  {nodeLabel(graph, anomaly.node)}
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
