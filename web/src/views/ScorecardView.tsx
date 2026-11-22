// Y5 · The bench scorecard: Argus against a threshold baseline on sealed worlds whose truth was committed by
// hash before any agent ran. Reads the latest result from GET /bench/scorecard.

import { useEffect, useState } from "react";
import { dayLabel, hhmm } from "../lib/format";
import { views } from "./data";
import { useText } from "../settings/language";
import { AGENT_TEXT, foldLabels, misses, SCENARIO_TEXT, scenarioLines, summaryMetrics, type Scorecard } from "./scorecard";

export function ScorecardView() {
  const [card, setCard] = useState<Scorecard | null>();
  const [error, setError] = useState<string | null>(null);
  const tr = useText();

  useEffect(() => {
    let live = true;
    views.benchResults().then(
      (d) => live && setCard(d),
      (e: Error) => live && setError(`The scorecard could not be loaded: ${e.message}.`),
    );
    return () => {
      live = false;
    };
  }, []);

  const evidence = <section className="sc-agent" aria-label={tr("Pre-registered result")}>
    <div className="sc-agent-head">
      <h3>{tr("Pre-registered result")}</h3>
      <a href="/?challenge=reveal" className="btn">{tr("Hash check")}</a>
    </div>
    <p className="vw-sub">{tr("Compare the revealed answer key with the hash published before the investigation.")}</p>
  </section>;
  if (error || !card) return (
    <section className="vw sc" aria-label="Track record">
      <div className="vw-scroll"><div className="sc-page">
        {evidence}
        <p className={error ? "vw-error" : "vw-sub"}>{error ?? (card === undefined ? "Loading the scorecard…" : "Benchmark results are unavailable.")}</p>
      </div></div>
    </section>
  );
  const lines = scenarioLines(card);
  const argusMisses = misses(card, "argus");

  return (
    <section className="vw sc" aria-label="bench scorecard">
      <div className="vw-scroll">
        <div className="sc-page">
          <header className="sc-head">
            <div>
              <h2 className="vw-title">Track record</h2>
              <p className="vw-sub">
                Every scenario on {card.seeds.length} seeds. The hidden truth of each world was hashed before any agent ran and
                revealed after; the bench grades against it.
              </p>
            </div>
            <span className="tv-fill" />
            <span className="sc-source live">
              Latest bench run · {dayLabel(card.created_at)} {hhmm(card.created_at)} · commit {card.git_commit.slice(0, 7)}
            </span>
          </header>
          {evidence}

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
                      if (!cell) return <td key={a} className="muted" data-label={AGENT_TEXT[a] ?? a}>not run</td>;
                      const r = cell.row;
                      return (
                        <td key={a} className={`sc-cell t-${cell.tone}`} data-label={AGENT_TEXT[a] ?? a}>
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
