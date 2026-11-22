// Y5 · The bench scorecard: Argus against a threshold baseline on sealed worlds whose truth was committed by
// hash before any agent ran. Reads GET /bench/results; until that route is built it shows a recorded sample,
// labelled as such. Misses are shown in red, never filtered out.

import { useEffect, useState } from "react";
import { dayLabel, hhmm } from "../lib/format";
import { views } from "./data";
import sampleUrl from "./fixtures/scorecard.sample.json?url";
import { AGENT_TEXT, foldLabels, isScorecard, misses, SCENARIO_TEXT, scenarioLines, summaryMetrics, type Scorecard } from "./scorecard";

type Source = { kind: "live" } | { kind: "sample"; why: string };

async function loadScorecard(): Promise<{ card: Scorecard; source: Source }> {
  let why = "GET /bench/results is not built yet";
  try {
    const live = await views.benchResults();
    if (isScorecard(live)) return { card: live, source: { kind: "live" } };
    why = "GET /bench/results did not return a scorecard";
  } catch {
    /* 501 stub, not proxied, or offline: use the recorded sample */
  }
  const res = await fetch(sampleUrl);
  const sample: unknown = await res.json();
  if (!isScorecard(sample)) throw new Error("the recorded sample is not a scorecard");
  return { card: sample, source: { kind: "sample", why } };
}

export function ScorecardView() {
  const [data, setData] = useState<{ card: Scorecard; source: Source } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    loadScorecard().then(
      (d) => live && setData(d),
      (e: Error) => live && setError(`The scorecard could not be loaded: ${e.message}.`),
    );
    return () => {
      live = false;
    };
  }, []);

  if (error) return <div className="vw-error">{error}</div>;
  if (!data) return <div className="vw-empty">Loading the scorecard…</div>;
  const { card, source } = data;
  const lines = scenarioLines(card);
  const argusMisses = misses(card, "argus");

  return (
    <section className="vw sc" aria-label="bench scorecard">
      <div className="vw-scroll">
        <div className="sc-page">
          <header className="sc-head">
            <div>
              <h2 className="vw-title">Bench scorecard</h2>
              <p className="vw-sub">
                Every scenario on {card.seeds.length} sealed seeds. The hidden truth of each world was hashed before any agent ran and
                revealed after; the bench grades against it.
              </p>
            </div>
            <span className="tv-fill" />
            {source.kind === "sample" ? (
              <span className="sc-source sample" title={source.why}>
                Recorded {dayLabel(card.created_at)} {hhmm(card.created_at)} · commit {card.git_commit.slice(0, 7)}
              </span>
            ) : (
              <span className="sc-source live">Latest bench run · commit {card.git_commit.slice(0, 7)}</span>
            )}
          </header>

          <div className="sc-agents">
            {card.summaries.map((s) => (
              <div key={s.agent} className={`sc-agent a-${s.agent}`}>
                <div className="sc-agent-head">
                  <h3>{AGENT_TEXT[s.agent] ?? s.agent}</h3>
                  <span className={`sc-verified${s.all_verified ? " ok" : " bad"}`}>
                    {s.all_verified ? "✓ every truth matched its commitment" : "✗ a commitment did not verify"}
                  </span>
                </div>
                <div className="sc-metrics">
                  {summaryMetrics(s).map((m) => (
                    <div key={m.key} className={`sc-metric t-${m.tone}`} title={m.hint}>
                      <span className="sc-metric-value">{m.value}</span>
                      <span className="sc-metric-label">{m.label}</span>
                      <span className="sc-metric-hint">{m.hint}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="sc-table-wrap">
            <table className="sc-table">
              <thead>
                <tr>
                  <th>Scenario</th>
                  {card.agents.map((a) => (
                    <th key={a}>{AGENT_TEXT[a] ?? a}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={line.scenario}>
                    <th scope="row">
                      <span className="mono">{line.scenario}</span>
                      <span className="sc-scn">{SCENARIO_TEXT[line.scenario] ?? line.scenario}</span>
                    </th>
                    {card.agents.map((a) => {
                      const cell = line.cells[a];
                      if (!cell) return <td key={a} className="muted">not run</td>;
                      const r = cell.row;
                      return (
                        <td key={a} className={`sc-cell t-${cell.tone}`}>
                          <div className="sc-pass">
                            <b>{cell.passLabel}</b> passed
                            <span className="muted" title="chance that k runs of this scenario all pass (pass^k)">
                              {" "}
                              · pass<sup>{r.k}</sup> {Math.round(r.pass_hat_k * 100)}%
                            </span>
                          </div>
                          <div className="sc-labels">
                            {foldLabels(r.verdicts).map(([label, n], i) => (
                              <span key={i} className={`sc-label l-${label.replace(/[^a-z]/gi, "_")}`}>
                                {n > 1 ? `${n}× ` : ""}
                                {label}
                              </span>
                            ))}
                          </div>
                          <div className="sc-sub muted">
                            {r.ttd_median_h !== null ? `detected in ${r.ttd_median_h} h (median)` : "no fault to detect"}
                            {r.false_alarms > 0 ? ` · ${r.false_alarms} false alarm${r.false_alarms > 1 ? "s" : ""}` : " · 0 false alarms"}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {argusMisses.length > 0 && (
            <div className="sc-misses">
              <b>Where Argus still misses:</b>{" "}
              {argusMisses.map((r) => `${SCENARIO_TEXT[r.scenario] ?? r.scenario} (${r.passed}/${r.runs} passed: ${r.verdicts.join(", ")})`).join("; ")}.
              Shown on purpose: a scorecard that hides its failures proves nothing.
            </div>
          )}

          {card.unavailable && Object.keys(card.unavailable).length > 0 && (
            <div className="sc-sub muted">
              Not run: {Object.entries(card.unavailable).map(([a, why]) => `${a} (${why})`).join("; ")}
            </div>
          )}

          <div className="sc-commit">
            <label>Bench commitment, printed before any agent ran</label>
            <code>{card.bench_commitment}</code>
          </div>
          <div className="sc-sub muted">
            Seeds {card.seeds.join(", ")} · reproduce with <code>uv run argus-bench run --runs {card.seeds.length}</code> and check any case with{" "}
            <code>uv run argus-bench verify runs/bench/&lt;case&gt;</code>.
          </div>
        </div>
      </div>
    </section>
  );
}
