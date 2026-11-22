// The incident report, rendered from the structured findings: every number is a receipt.

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { dayLabel, eur, hhmm, humanize, impactNoun, pct, segmentLabel, share, verdictLabel } from "../lib/format";
import { isRuledOut, type IncidentView } from "../lib/store";
import type { Graph, Incident, IncidentState, TrailStep } from "../lib/types";
import { Bars, TimeChart, type SeriesPoint } from "./charts";
import { Segments } from "./Feed";
import { Num, ReceiptChips } from "./Receipts";

const LIFECYCLE: IncidentState[] = ["open", "investigating", "explained", "monitoring", "resolved"];

function stepData<T>(trail: TrailStep[], kind: string): T | null {
  const step = trail.find((s) => s.kind === kind);
  return step ? (step.data as T) : null;
}

interface PathCell {
  segment: Record<string, string>;
  ep: number;
  volume_share: number;
  rel_change: number;
}

export function IncidentSheet({
  id,
  summary,
  graph,
  onClose,
}: {
  id: string;
  summary: IncidentView | undefined;
  graph: Graph | null;
  onClose: () => void;
}) {
  const [incident, setIncident] = useState<Incident | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const version = summary?.lastSeq ?? 0;

  useEffect(() => {
    let live = true;
    api.incident(id).then(
      (i) => {
        if (!live) return;
        setIncident(i);
        setError(null);
      },
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [id, version]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copy = async () => {
    const md = await api.report(id);
    await navigator.clipboard.writeText(md);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  const f = incident?.findings;
  const money = f?.impact && incident ? impactNoun(f.impact.node, incident.direction, graph) : "";
  const path = f ? (stepData<{ path: PathCell[] }>(f.trail, "segment")?.path ?? []) : [];
  const series = f ? (stepData<{ series: SeriesPoint[] }>(f.trail, "impact")?.series ?? []) : [];
  const reached = incident ? new Set(incident.history.map((h) => h.to_state)) : new Set<IncidentState>();
  const when = (state: IncidentState) => incident?.history.find((h) => h.to_state === state)?.sim_ts;

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <section className="sheet" role="dialog" aria-label={`Incident ${id}`}>
        <div className="sheet-head">
          <div className="sheet-top">
            <span className="mono">{id}</span>
            {incident && <span className={`pill state-${incident.state}`}>{incident.state}</span>}
            {incident && <span className={`pill ${incident.verdict}`}>{verdictLabel(incident.verdict)}</span>}
            <span className="spacer" />
            <button className="btn" onClick={copy} disabled={!incident}>
              {copied ? "Copied" : "Copy report (Markdown)"}
            </button>
            <button className="icon-btn" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
          <h2 className="sheet-title">{incident?.title ?? summary?.title ?? "Loading…"}</h2>
          {incident && (
            <div className="sheet-meta">
              <span>
                severity <b>{eur(incident.severity_eur)}</b>
              </span>
              <span>
                opened <b>{`${dayLabel(incident.opened_at)} ${hhmm(incident.opened_at)}`}</b>
              </span>
              <span>
                fingerprint <b>{incident.fingerprint}</b>
              </span>
            </div>
          )}
          {incident && (
            <div className="lifecycle">
              {LIFECYCLE.map((s) => (
                <div key={s} className={`lc${reached.has(s) ? " done" : ""}${incident.state === s ? " now" : ""}`}>
                  <b>{s}</b>
                  <span className="mono">{when(s) ? hhmm(when(s)) : ""}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="sheet-body">
          {error && <p className="muted">{error}</p>}
          {f && incident && (
            <>
              <div className="sec">
                <h3>What happened</h3>
                <div className="prose">
                  <strong>{f.headline}.</strong> <span className="mono">{f.observed.node}</span> for{" "}
                  {segmentLabel(f.observed.segment)} was <Num q={f.observed.observed} /> against an expected{" "}
                  <Num q={f.observed.expected} /> (<Num q={f.observed.change_pct} />){" "}
                  {f.window.start === f.window.end
                    ? `in the hour from ${hhmm(f.window.start)}`
                    : `from ${hhmm(f.window.start)} to ${hhmm(f.window.end)}`}
                  .
                  {f.root && (
                    <>
                      {" "}
                      The change sits in <strong>{segmentLabel(f.root.segment)}</strong>, where it is{" "}
                      <Num q={f.root.change_pct} />.
                    </>
                  )}
                </div>
                {f.root?.evidence && (
                  <div className="evidence">
                    <div>
                      <div>{f.root.evidence.description}</div>
                      <div className="mono">
                        {f.root.evidence.log} · {f.root.evidence.ref} · {hhmm(f.root.evidence.ts)}
                      </div>
                    </div>
                  </div>
                )}
                {series.length > 1 && (
                  <div style={{ marginTop: 14 }}>
                    <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                      {humanize(f.root?.node ?? f.observed.node)} in {segmentLabel(f.root?.segment ?? f.observed.segment)}, hourly,
                      against the same hour of the last 4 weeks (dashed)
                    </div>
                    <TimeChart points={series} onset={f.window.start} />
                  </div>
                )}
              </div>

              {f.impact && (
                <div className="sec">
                  <h3>Impact</h3>
                  <div className="kv">
                    <div>
                      <label>{humanize(f.impact.node)} per hour</label>
                      <span className="big">
                        <Num q={f.impact.per_hour} signed />
                      </span>
                    </div>
                    <div>
                      <label>{money.includes("GMV") ? "GMV" : "EUR"} per hour</label>
                      <span className="big">
                        <Num q={f.impact.gmv_eur_per_hour} />
                      </span>
                    </div>
                    <div>
                      <label>
                        {money.charAt(0).toUpperCase() + money.slice(1)} over {f.impact.hours} h
                      </label>
                      <span className="big">
                        <Num q={f.impact.eur_so_far} />
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {path.length > 0 && (
                <div className="sec">
                  <h3>Where it is</h3>
                  <div className="path">
                    {path.map((cell) => {
                      const [dim, value] = Object.entries(cell.segment).pop() ?? ["", ""];
                      return (
                        <div key={dim} className="path-cell">
                          <div className="dim">{dim}</div>
                          <div className="val">{value}</div>
                          <div className="ep">
                            <div style={{ width: share(cell.ep) }} />
                          </div>
                          <div className="meta">
                            {share(cell.ep)} of the loss · {share(cell.volume_share, 1)} of the volume · {pct(100 * cell.rel_change)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {f.decomposition.length > 0 && (
                <div className="sec">
                  <h3>Where the change came from</h3>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                    Exact LMDI split of the change in <span className="mono">{f.decomposed_node}</span> for{" "}
                    {segmentLabel(f.impact?.segment ?? f.root?.segment ?? {})}: the shares sum to 100%, nothing is left over.
                  </div>
                  <Bars
                    data={[...f.decomposition]
                      .sort((a, b) => Math.abs(b.share) - Math.abs(a.share))
                      .map((c, i) => ({
                        label: humanize(c.node),
                        value: c.share,
                        lead: i === 0,
                        right: <Num q={{ value: 100 * c.share, unit: "pct", receipt: c.receipt }} text={`${(100 * c.share).toFixed(1)}%`} />,
                      }))}
                  />
                </div>
              )}

              <div className="sec">
                <h3>Ruled out</h3>
                <div className="ruled">
                  {f.ruled_out.map((r) => (
                    <div key={r.hypothesis} className="ruled-item">
                      <div className="h">{r.hypothesis}</div>
                      <div className="p">Predicted: {r.prediction}</div>
                      <div className="r">
                        {r.reason} <ReceiptChips ids={r.receipts} />
                      </div>
                    </div>
                  ))}
                  {!f.ruled_out.length && <div className="muted">Nothing ruled out.</div>}
                </div>
              </div>

              {f.skeptic && (
                <div className="sec">
                  <h3>Skeptic · {f.skeptic.verdict}</h3>
                  <ul className="list">
                    {f.skeptic.checks.map((c) => (
                      <li key={c.check}>
                        <strong>{c.check}</strong>: {c.result} <ReceiptChips ids={c.receipts} max={2} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="sec">
                <h3>Still uncertain</h3>
                <ul className="list">
                  {f.uncertain.map((u) => (
                    <li key={u}>{u}</li>
                  ))}
                  <li>
                    Explained {share(f.explained_share)}, unexplained {share(f.unexplained_share)}: the remainder is reported, not
                    hidden.
                  </li>
                </ul>
              </div>

              {f.suggested_action && (
                <div className="sec">
                  <h3>Suggested action</h3>
                  <div className="action">
                    <span className="pill">{f.suggested_action.needs_approval ? "needs your approval" : "automatic"}</span>
                    <span>{f.suggested_action.text.replace(/\.?$/, ".")}</span>
                  </div>
                </div>
              )}

              <div className="sec">
                <h3>Investigation trail</h3>
                <div className="full-trail">
                  {f.trail.map((s) => (
                    <article key={s.step} className="tstep">
                      <div className="tstep-head">
                        <span className="tstep-n">{s.step}</span>
                        <span className="tstep-kind">{humanize(s.kind)}</span>
                        <span className="mono" style={{ marginLeft: "auto" }}>
                          {s.tool}
                        </span>
                      </div>
                      {s.prediction && <div className="tstep-pred">Predicts: {s.prediction}</div>}
                      <div className="tstep-result">{s.result}</div>
                      <div className={`tstep-decision${isRuledOut(s.decision) ? " refuted" : ""}`}>
                        <span>{isRuledOut(s.decision) ? "✗" : "→"}</span>
                        <span>
                          {s.decision}
                          {s.why ? ` (${s.why})` : ""}
                        </span>
                      </div>
                      <ReceiptChips ids={s.receipts} />
                    </article>
                  ))}
                </div>
                <p className="muted" style={{ fontSize: 12 }}>
                  {f.cost.queries} queries · {f.cost.seconds.toFixed(2)} s · {f.cost.llm_calls} LLM calls · €{f.cost.eur.toFixed(2)}. The
                  math decides; a model may only write prose.
                </p>
                <Segments segment={incident.segment} />
              </div>
            </>
          )}
        </div>
      </section>
    </>
  );
}
