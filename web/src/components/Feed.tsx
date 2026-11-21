// The right rail: incidents, "didn't wake you" notes and graph changes, newest first.

import { useState } from "react";
import { eur, hhmm, segmentEntries } from "../lib/format";
import { type EdgeChange, type FeedItem, type IncidentView, type RunView } from "../lib/store";
import type { Note } from "../lib/types";
import { Num, ReceiptChips } from "./Receipts";

type Tab = "all" | "incidents" | "quiet" | "graph";

export function Segments({ segment }: { segment: Record<string, string> }) {
  const entries = segmentEntries(segment);
  if (!entries.length) return null;
  return (
    <div className="segs">
      {entries.map(([k, v]) => (
        <span key={k} className="seg">
          <i>{k}</i>
          {v}
        </span>
      ))}
    </div>
  );
}

const STATE_TEXT: Record<string, string> = {
  open: "open",
  investigating: "investigating",
  explained: "explained",
  monitoring: "monitoring",
  resolved: "resolved",
};

function IncidentCard({ inc, onOpen }: { inc: IncidentView; onOpen: (id: string) => void }) {
  return (
    <article className={`card incident click ${inc.state}`} onClick={() => onOpen(inc.id)}>
      <div className="card-head">
        <span className="card-kind">{inc.id}</span>
        <span className={`pill state-${inc.state}`}>{STATE_TEXT[inc.state]}</span>
        <span className={`pill ${inc.verdict}`}>{inc.verdict.replace("_", " ")}</span>
        <span className="card-time">{hhmm(inc.updatedAt)}</span>
      </div>
      <div className="card-title">{inc.title}</div>
      <Segments segment={inc.segment} />
      <div className="inc-money">
        {inc.severity_eur > 0 ? (
          <>
            <b>{eur(inc.severity_eur)}</b>
            <span>{inc.state === "resolved" ? "GMV lost in total" : "GMV lost so far"} · open the report</span>
          </>
        ) : (
          <span>measuring the impact…</span>
        )}
      </div>
      {inc.reason && <div className="card-body">{inc.reason.replace(/ \[r\d+\]/g, "")}</div>}
    </article>
  );
}

function noteKind(note: Note): { key: string; label: string } {
  if (note.kind === "expected") return { key: "expected", label: "Didn't wake you" };
  if (note.kind === "data_issue") return { key: "data_issue", label: "Data issue · held back" };
  if (note.reason.includes("symptom of")) return { key: "symptom", label: "Symptom silenced" };
  return { key: "suppressed", label: "Noticed, not paged" };
}

function Gauge({ z, alarm }: { z: number; alarm: number }) {
  const scale = alarm * 1.25;
  const fill = Math.min(Math.abs(z) / scale, 1) * 100;
  return (
    <div className="gauge" title={`|z| ${Math.abs(z).toFixed(1)} against the alarm line ${alarm}`}>
      <span>|z| {Math.abs(z).toFixed(1)}</span>
      <span className="gauge-bar">
        <span className="gauge-fill" style={{ width: `${fill}%`, opacity: 0.85 }} />
        <span className="gauge-line" style={{ left: `${(alarm / scale) * 100}%` }} />
      </span>
      <span>alarm {alarm}</span>
    </div>
  );
}

function NoteCard({ note, alarm }: { note: Note; alarm: number }) {
  const kind = noteKind(note);
  const z = note.numbers.find((n) => n.unit === "z");
  const values = note.numbers.filter((n) => n.unit !== "z");
  return (
    <article className={`card note-${kind.key}`}>
      <div className="card-head">
        <span className="card-kind">{kind.label}</span>
        {note.node && <span className="mono">{note.node}</span>}
        <span className="card-time">{hhmm(note.sim_ts)}</span>
      </div>
      <div className="card-body" style={{ marginTop: 0 }}>
        {note.reason}
      </div>
      {values.length >= 2 && (
        <div className="nums">
          <span>
            observed <Num q={values[0]} />
          </span>
          <span>
            expected <Num q={values[1]} />
          </span>
        </div>
      )}
      {z && <Gauge z={z.value} alarm={alarm} />}
    </article>
  );
}

function testValue(c: EdgeChange): string {
  const r = c.result;
  if (r.median_rel !== null && r.p95_rel !== null) {
    return `residual ${(100 * r.median_rel).toFixed(2)}% median, ${(100 * r.p95_rel).toFixed(2)}% p95 over ${r.hours} h`;
  }
  if (r.max_rel_err !== null) return `children sum within ${(100 * r.max_rel_err).toFixed(3)}% over ${r.hours} h`;
  return r.note || "status changed";
}

function EdgesCard({ changes, simTs }: { changes: EdgeChange[]; simTs: string }) {
  const [open, setOpen] = useState(changes.length <= 3);
  const firstRun = changes.every((c) => c.from === null);
  const broken = changes.filter((c) => c.to === "BROKEN").length;
  const summary = firstRun
    ? `${changes.length} edge tests ran: ${changes.length - broken} hold${broken ? `, ${broken} broken` : ""}`
    : `${changes.length} edge ${changes.length === 1 ? "status changed" : "statuses changed"}`;
  return (
    <article className="card click" onClick={() => setOpen(!open)}>
      <div className="card-head">
        <span className="card-kind">Graph change</span>
        <span className="card-time">{hhmm(simTs)}</span>
      </div>
      <div className="card-title">{summary}</div>
      <div className="card-body">
        {firstRun
          ? "Every formula and breakdown is a contract, re-tested against the data. Before → after, with the test value."
          : "An edge only changes state when its test says so."}
      </div>
      {open && (
        <div className="edge-list" onClick={(e) => e.stopPropagation()}>
          {changes.map((c) => (
            <div key={`${c.edge}-${c.seq}`} className="edge-row">
              <span className="mono" title={c.edge}>
                {c.edge}
              </span>
              <span className="transition">
                <span className={`st ${c.from ?? ""}`}>{c.from ?? "untested"}</span>→<span className={`st ${c.to}`}>{c.to}</span>
              </span>
              <span className="edge-test">
                {testValue(c)} <ReceiptChips ids={c.result.receipts} max={2} />
              </span>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

function FeedCard({ item, view, onOpen }: { item: FeedItem; view: RunView; onOpen: (id: string) => void }) {
  if (item.kind === "incident") {
    const inc = view.incidents[item.id];
    return inc ? <IncidentCard inc={inc} onOpen={onOpen} /> : null;
  }
  if (item.kind === "note") return <NoteCard note={item.note} alarm={view.thresholds.alarm_z} />;
  return <EdgesCard changes={item.changes} simTs={item.simTs} />;
}

export function Feed({ view, onOpenIncident }: { view: RunView; onOpenIncident: (id: string) => void }) {
  const [tab, setTab] = useState<Tab>("all");
  const items = [...view.feed].reverse();
  const quiet = items.filter((i) => i.kind === "note");
  const graph = items.filter((i) => i.kind === "edges");
  const incidents = items.filter((i) => i.kind === "incident");
  const shown = tab === "all" ? items : tab === "incidents" ? incidents : tab === "quiet" ? quiet : graph;
  const tabs: [Tab, string, number][] = [
    ["all", "Feed", items.length],
    ["incidents", "Incidents", incidents.length],
    ["quiet", "Didn't wake you", quiet.length],
    ["graph", "Graph", graph.reduce((n, i) => n + (i.kind === "edges" ? i.changes.length : 0), 0)],
  ];
  return (
    <aside className="rail">
      <nav className="tabs">
        {tabs.map(([key, label, n]) => (
          <button key={key} className={`tab${tab === key ? " on" : ""}`} onClick={() => setTab(key)}>
            {label}
            <span className="count">{n}</span>
          </button>
        ))}
      </nav>
      <div className="feed">
        {shown.length ? (
          shown.map((item) => (
            <FeedCard
              key={item.kind === "incident" ? `inc-${item.id}` : `${item.kind}-${item.seq}`}
              item={item}
              view={view}
              onOpen={onOpenIncident}
            />
          ))
        ) : (
          <div className="feed-empty">Nothing here yet.</div>
        )}
      </div>
    </aside>
  );
}
