// Y4 · "While you slept" as a full, printable page: the digest, every incident with its report, and every
// change Argus deliberately did not wake anyone for. Every number keeps its receipt.

import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { Segments } from "../components/Feed";
import { Num, ReceiptChips, useOpenReceipt } from "../components/Receipts";
import { api, type Digest } from "../lib/api";
import { dayLabel, eur, hhmm, share } from "../lib/format";
import type { RunView } from "../lib/store";
import type { Incident, Note } from "../lib/types";
import { explain, views } from "./data";
import { parseMarkdown, type Block, type Inline } from "./markdown";
import { plainWords } from "../fx/workspace/plain";

const VERDICT_TEXT: Record<string, string> = {
  SUPPORTED_CAUSE: "Supported cause",
  HYPOTHESIS: "Hypothesis",
  EXPECTED: "Expected",
  DATA_ISSUE: "Data issue",
  UNEXPLAINED: "Unexplained",
};

function noteLabel(note: Note): string {
  if (note.kind === "expected") return "Didn't wake you · expected";
  if (note.kind === "data_issue") return "Didn't wake you · data issue";
  if (note.reason.includes("symptom of")) return "Silenced · symptom of an open incident";
  return "Noticed, not paged";
}

function Inlines({ parts }: { parts: Inline[] }) {
  const openReceipt = useOpenReceipt();
  return (
    <>
      {parts.map((p, i) => {
        if (p.t === "code") return <code key={i}>{p.v}</code>;
        if (p.t === "bold") return <strong key={i}>{p.v}</strong>;
        if (p.t === "receipt")
          return (
            <button key={i} className="rcpt" title="Open the query behind this number" onClick={() => openReceipt(p.v)}>
              {p.v}
            </button>
          );
        return <Fragment key={i}>{p.v}</Fragment>;
      })}
    </>
  );
}

export function Markdown({ blocks }: { blocks: Block[] }) {
  return (
    <div className="md">
      {blocks.map((b, i): ReactNode => {
        switch (b.t) {
          case "h": {
            const H = b.level === 1 ? "h3" : b.level === 2 ? "h4" : "h5";
            return (
              <H key={i}>
                <Inlines parts={b.inline} />
              </H>
            );
          }
          case "p":
            return (
              <p key={i}>
                <Inlines parts={b.inline} />
              </p>
            );
          case "ul":
          case "ol": {
            const L = b.t;
            return (
              <L key={i}>
                {b.items.map((item, j) => (
                  <li key={j}>
                    <Inlines parts={item} />
                  </li>
                ))}
              </L>
            );
          }
          case "table":
            return (
              <div key={i} className="md-table">
                <table>
                  <thead>
                    <tr>
                      {b.head.map((c, j) => (
                        <th key={j}>
                          <Inlines parts={c} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, j) => (
                      <tr key={j}>
                        {row.map((c, k) => (
                          <td key={k}>
                            <Inlines parts={c} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </div>
  );
}

function IncidentReport({ incident, onOpenIncident }: { incident: Incident; onOpenIncident: (id: string) => void }) {
  const [md, setMd] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const f = incident.findings;

  useEffect(() => {
    let live = true;
    api.report(incident.id).then(
      (text) => live && (setMd(text), setFailed(false)),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [incident.id, incident.updated_at, incident.state]);

  const blocks = useMemo(() => (md ? parseMarkdown(md) : []), [md]);
  // the report repeats the title as its first heading; the card already shows it
  const body = blocks[0]?.t === "h" && blocks[0].level === 1 ? blocks.slice(1) : blocks;

  return (
    <article className={`mr-incident v-${incident.verdict}`}>
      <div className="mr-inc-head">
        <span className="mono">{incident.id}</span>
        <span className={`pill ${incident.verdict}`}>{VERDICT_TEXT[incident.verdict] ?? incident.verdict}</span>
        <span className={`pill state-${incident.state}`}>{incident.state}</span>
        <span className="tv-fill" />
        <button className="btn no-print" onClick={() => onOpenIncident(incident.id)}>
          Open in Mission Control
        </button>
      </div>
      <h3 className="mr-inc-title">{incident.title}</h3>
      <Segments segment={incident.segment} />
      <div className="mr-kv">
        <div>
          <label>GMV lost while open</label>
          <span className="big">{eur(incident.severity_eur)}</span>
        </div>
        {f.impact && (
          <div>
            <label>GMV per hour</label>
            <span className="big">
              <Num q={f.impact.gmv_eur_per_hour} />
            </span>
          </div>
        )}
        <div>
          <label>explained</label>
          <span className="big">{share(f.explained_share)}</span>
        </div>
        <div>
          <label>unexplained, stated not hidden</label>
          <span className="big">{share(f.unexplained_share)}</span>
        </div>
      </div>
      <div className="mr-when muted">
        opened {dayLabel(incident.opened_at)} {hhmm(incident.opened_at)}
        {incident.resolved_at ? ` · resolved ${dayLabel(incident.resolved_at)} ${hhmm(incident.resolved_at)}` : ` · ${incident.state}`}
      </div>
      {f.ruled_out.length > 0 && (
        <div className="mr-ruled">
          <div className="mr-label">Ruled out</div>
          {f.ruled_out.map((r) => (
            <div key={r.hypothesis} className="mr-ruled-item">
              <span className="struck">{r.hypothesis}</span>
              <span className="muted"> · {r.reason}</span> <ReceiptChips ids={r.receipts} max={3} />
            </div>
          ))}
        </div>
      )}
      {f.suggested_action && (
        <div className="mr-action">
          <span className="pill">{f.suggested_action.needs_approval ? "needs your approval" : "automatic"}</span>
          {f.suggested_action.text}
        </div>
      )}
      <button className="mr-toggle no-print" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? "Hide the full report" : "Read the full report"}
      </button>
      <div className={`mr-report${open ? " open" : ""}`}>
        {md ? <Markdown blocks={body} /> : <div className="muted">{failed ? "The report could not be loaded." : "Loading the report…"}</div>}
      </div>
    </article>
  );
}

export function MorningReport({ view, onOpenIncident }: { view: RunView; onOpenIncident: (id: string) => void }) {
  const [digest, setDigest] = useState<Digest | null>(null);
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // re-read when something the page shows changed: an incident moved, a note arrived, or six more hours passed
  const incidentSeq = Object.values(view.incidents).reduce((m, i) => Math.max(m, i.lastSeq), 0);
  const version = `${view.stream}:${incidentSeq}:${view.notes.length}:${Math.floor(view.ticks / 6)}`;

  useEffect(() => {
    let live = true;
    Promise.all([api.digest(), views.incidents(), views.notes()]).then(
      ([d, i, n]) => {
        if (!live) return;
        setDigest(d);
        setIncidents([...i].sort((a, b) => a.opened_at.localeCompare(b.opened_at)));
        setNotes(n);
        setError(null);
      },
      (e: unknown) => live && setError(explain(e, "The morning report")),
    );
    return () => {
      live = false;
    };
  }, [version]);

  const alarm = view.thresholds.alarm_z;
  return (
    <section className="vw mr" aria-label="morning report">
      <div className="vw-scroll">
        <div className="mr-page">
          <header className="mr-head">
            <div>
              <div className="mr-kicker">Argus · morning report</div>
              <h1>{digest?.title.replace(/\s*\(.*\)\s*$/, "") || "While you slept"}</h1>
              <p className="muted">
                {digest?.since && digest.until
                  ? `${dayLabel(digest.since)} ${hhmm(digest.since)} to ${dayLabel(digest.until)} ${hhmm(digest.until)} (simulated time)`
                  : "Everything Argus did on its own, one line each."}
              </p>
            </div>
            <div className="mr-actions no-print">
              <button className="btn" disabled={!digest} onClick={() => digest && void navigator.clipboard.writeText(digest.markdown)}>
                Copy as Markdown
              </button>
              <button className="btn primary" onClick={() => window.print()}>
                Print
              </button>
            </div>
          </header>

          {error && !digest && <div className="vw-error">{error}</div>}
          {!digest && !error && <div className="vw-empty">Loading the morning report…</div>}

          {digest && (
            <div className="mr-digest">
              {digest.lines.map((line) => (
                <div key={line.key} className={`mr-line ${line.tone}`}>
                  <span className="mr-line-label">{line.label}</span>
                  <span className="mr-line-value">{plainWords(line.value)}</span>
                  <span className="mr-line-detail">
                    {plainWords(line.detail)}
                    {line.receipts.length > 0 ? (
                      <ReceiptChips ids={line.receipts} max={5} />
                    ) : (
                      <span className="muted mr-nocount"> · a count of what the monitor did, no query behind it</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}

          {incidents && (
            <>
              <h2 className="mr-h2">
                Incidents <span className="muted">· {incidents.length}</span>
              </h2>
              {incidents.length ? (
                incidents.map((inc) => <IncidentReport key={inc.id} incident={inc} onOpenIncident={onOpenIncident} />)
              ) : (
                <div className="mr-quiet">No incident. Nothing crossed the alarm line long enough to page anyone.</div>
              )}
            </>
          )}

          {notes && (
            <>
              <h2 className="mr-h2">
                Didn't wake you <span className="muted">· {notes.length}</span>
              </h2>
              {notes.length ? (
                <div className="mr-notes">
                  {notes.map((note) => {
                    const z = note.numbers.find((n) => n.unit === "z");
                    const values = note.numbers.filter((n) => n.unit !== "z");
                    const scale = alarm * 1.25;
                    return (
                      <article key={note.id} className={`mr-note k-${note.kind}`}>
                        <div className="mr-note-head">
                          <span className="mr-label">{noteLabel(note)}</span>
                          {note.node && <span className="mono">{note.node}</span>}
                          <span className="tv-fill" />
                          <span className="mono muted">
                            {dayLabel(note.sim_ts)} {hhmm(note.sim_ts)}
                          </span>
                        </div>
                        <div className="mr-note-reason">{note.reason}</div>
                        <Segments segment={note.segment} />
                        {values.length > 0 && (
                          <div className="mr-note-nums">
                            {values.map((q, i) => (
                              <Num key={i} q={q} />
                            ))}
                          </div>
                        )}
                        {z && (
                          <div className="mr-gauge" title={`|z| ${Math.abs(z.value).toFixed(1)} against the alarm line ${alarm}`}>
                            <span>
                              <Num q={{ ...z, value: Math.abs(z.value) }} text={`|z| ${Math.abs(z.value).toFixed(1)}`} />
                            </span>
                            <span className="gauge-bar">
                              <span className="gauge-fill" style={{ width: `${Math.min(Math.abs(z.value) / scale, 1) * 100}%` }} />
                              <span className="gauge-line" style={{ left: `${(alarm / scale) * 100}%` }} />
                            </span>
                            <span className="muted">alarm line {alarm}</span>
                          </div>
                        )}
                        {note.receipts.length > 0 && <ReceiptChips ids={note.receipts} max={4} />}
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className="mr-quiet">No held-back alerts in this run.</div>
              )}
            </>
          )}

          <footer className="mr-foot muted">
            Counts come from the event stream; money and verdicts come from queries with receipts. Click any receipt to see its SQL.
          </footer>
        </div>
      </div>
    </section>
  );
}
