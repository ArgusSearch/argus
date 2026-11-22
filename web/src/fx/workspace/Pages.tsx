// The incident list (everything Argus filed, and the alerts it held back on purpose) and the glossary page.

import { useAppState } from "../../lib/AppState";
import { eur, dayLabel, hhmm, monitoringText } from "../../lib/format";
import type { RunView } from "../../lib/store";
import type { Graph, Note } from "../../lib/types";
import { openIncidentPage } from "../nav";
import { GLOSSARY, incidentWhere, metricName, STATE, storyHeadline, VERDICT, wherePhrase } from "./plain";
import { Card, Pill, Term, useIncidents } from "./ui";

const HELD: Record<Note["kind"], { label: string; help: string }> = {
  expected: { label: "Planned change", help: "A plan explained the move and delivery followed it." },
  data_issue: { label: "Late data", help: "The data had not fully arrived; Argus waited for it." },
  suppressed: { label: "Knock-on effect", help: "Moved only because of an incident already filed; one incident, not one per symptom." },
};

function heldReason(graph: Graph | null, { node, reason }: Note): string {
  reason = monitoringText(reason);
  if (!node) return reason;
  const name = metricName(graph, node);
  const label = graph?.nodes.find((metric) => metric.id === node)?.label ?? name;
  return [name, label].some((prefix) => reason.startsWith(`${prefix}: `)) ? reason : `${name}: ${reason}`;
}

export function IncidentsPage({ graph, view, onOpenIncident }: { graph: Graph | null; view: RunView; onOpenIncident: (id: string) => void }) {
  const { incidents } = useIncidents(view);
  const { monitor } = useAppState();
  const rows = monitor.incidents;
  const full = new Map(incidents.map((i) => [i.id, i]));
  const held = [...view.notes].reverse();
  return (
    <main className="fx-dash ws-page ws-incidents" aria-label="incidents">
      <header className="ws-head">
        <span className="fx-hud ws-kicker">Incidents</span>
        <h1>{rows.length ? `${monitor.openIncidents.length} open, ${rows.length - monitor.openIncidents.length} resolved`
          : monitor.activeInvestigation ? "Investigating a metric change"
          : !monitor.time ? "Waiting for shop data" : "No incidents yet"}</h1>
        <p>An incident is filed only when a key metric crosses the alarm threshold and Argus has checked why. Everything else is logged, not paged.</p>
      </header>
      <Card title="Filed incidents" className="ws-inc-card">
        {rows.length === 0 ? (
          <p className="fx-empty">Nothing crossed the alarm threshold long enough to page anyone.</p>
        ) : (
          <table className="ws-table">
            <thead>
              <tr>
                <th>Incident</th>
                <th>What happened</th>
                <th>Where</th>
                <th>Status</th>
                <th className="ws-num">Cost</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((inc) => {
                const whole = full.get(inc.id);
                const f = whole?.findings;
                const root = f?.root;
                const where = whole ? incidentWhere(whole) : inc.segment;
                return (
                  <tr key={inc.id} onClick={() => onOpenIncident(inc.id)}>
                    <td className="mono">
                      {inc.id}
                      <span className="ws-sub">
                        {dayLabel(full.get(inc.id)?.opened_at ?? inc.openedAt)} {hhmm(full.get(inc.id)?.opened_at ?? inc.openedAt)}
                      </span>
                    </td>
                    <td>
                      <b>{storyHeadline(graph, root?.node ?? inc.root_node, root?.change_pct.value ?? null, where)}</b>
                      {root?.evidence && <span className="ws-sub">Cause: {root.evidence.description}</span>}
                    </td>
                    <td data-label="Where">{wherePhrase(where)}</td>
                    <td>
                      <span className="ws-pills">
                        <Pill tone={STATE[inc.state].tone} title={STATE[inc.state].help}>
                          {STATE[inc.state].label}
                        </Pill>
                        <Pill tone={VERDICT[inc.verdict].tone} title={VERDICT[inc.verdict].help}>
                          {VERDICT[inc.verdict].label}
                        </Pill>
                      </span>
                    </td>
                    <td className="ws-num mono" data-label="Cost">{eur(Math.abs(inc.severity_eur))}</td>
                    <td>
                      <button
                        className="btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          openIncidentPage(inc.id);
                        }}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Held back: didn't wake you" className="ws-held-card">
        {held.length === 0 ? (
          <p className="fx-empty">No alert held back so far. When a move turns out to be planned, late data or a knock-on effect, it lands here instead of on your phone.</p>
        ) : (
          <ul className="ws-held">
            {held.map((n) => (
              <li key={n.id}>
                <Pill tone="muted" title={HELD[n.kind].help}>
                  {HELD[n.kind].label}
                </Pill>
                <span className="mono">
                  {dayLabel(n.sim_ts)} {hhmm(n.sim_ts)}
                </span>
                <span>{heldReason(graph, n)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </main>
  );
}

export function GlossaryPage() {
  return (
    <main className="fx-dash ws-page ws-glossary" aria-label="glossary">
      <header className="ws-head">
        <span className="fx-hud ws-kicker">Glossary</span>
        <h1>The words behind the numbers</h1>
        <p>
          The overview speaks plainly; the evidence pages use the exact terms. Each one below, with the plain words the overview uses instead. Hover a dotted word anywhere for the
          same explanation (<Term term="|z|" />
          ).
        </p>
      </header>
      <ul className="ws-gloss">
        {GLOSSARY.map((g) => (
          <li key={g.term}>
            <b>{g.plain}</b>
            {g.term !== g.plain && <span className="mono">{g.term}</span>}
            <p>{g.meaning}</p>
          </li>
        ))}
      </ul>
    </main>
  );
}
