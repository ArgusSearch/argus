// The village's DOM layer: the big status bubbles and name plates pinned over the igloos (positioned by the
// stage through the anchors map), the case-file tag, the role panel with its tool log, the approval card and
// the caption line. Text stays DOM so it is crisp in the video and selectable.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { AgentReceiptChips, ReceiptChips } from "../components/Receipts";
import { hhmm } from "../lib/format";
import { AgentAvatar } from "./avatars/AgentAvatar";
import { agentName, PERSONAS } from "./avatars/personas";
import { IDLE_AVATAR, type AvatarCue, type AvatarCues } from "./avatars/state";
import type { LogEntry, Outcome } from "./beats";
import type { Player } from "./player";
import { ROLE, ROLES, type RoleId } from "./roles";
import type { VillageState } from "./timeline";

/** A corner the pins keep clear of (the title block), in stage pixels from the top left. */
export interface Keepout {
  right: number;
  bottom: number;
}

/**
 * Moves a pinned element to (x, y) stage pixels. A column with a bubble needs room above its anchor, so it is
 * held below the top edge instead of sliding out of view. A bubble that would run into the title block slides
 * sideways past it (`--dodge`), while the name plate stays over its igloo.
 */
export function placePin(el: HTMLElement, x: number, y: number, visible = true, keepout: Keepout | null = null): void {
  const on = el.classList.contains("on");
  const tall = on ? 150 : 52;
  const yy = Math.max(tall, y);
  let dodge = 0;
  if (on && keepout && el.classList.contains("vl-pin-role") && yy - tall < keepout.bottom + 8) dodge = Math.max(0, Math.min(220, keepout.right + 12 - (x - 140)));
  el.style.transform = `translate3d(${x.toFixed(1)}px, ${yy.toFixed(1)}px, 0)`;
  el.style.setProperty("--dodge", `${dodge.toFixed(1)}px`);
  el.style.visibility = visible ? "visible" : "hidden";
}

/** The title block's corner, measured against the stage, for placePin. */
export function measureKeepout(stage: HTMLElement): Keepout | null {
  const hud = stage.closest(".vl-root")?.querySelector(".vl-hud-tl");
  if (!hud) return null;
  const a = stage.getBoundingClientRect();
  const b = hud.getBoundingClientRect();
  return { right: b.right - a.left, bottom: b.bottom - a.top };
}

/** Registers an element under `key` in the anchors map, for the stage to move. */
export function useAnchor(anchors: Map<string, HTMLElement>, key: string) {
  return (el: HTMLElement | null) => {
    if (el) anchors.set(key, el);
    else anchors.delete(key);
  };
}

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** The running clock of a WORKING bubble: playback time the role has been on its case. */
function Clock({ player, since }: { player: Player; since: number }) {
  const [now, setNow] = useState(player.time);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(player.time), 250);
    return () => window.clearInterval(timer);
  }, [player]);
  return <span className="vl-clock">{mmss(Math.max(0, now - since))}</span>;
}

export type BubbleKind = "working" | "need" | "finished" | null;

export interface RoleView {
  role: RoleId;
  kind: BubbleKind;
  line: string | null;
  since: number | null;
}

/** What each role's bubble shows at this moment. FINISHED stays for a few seconds after a role's part ends. */
export function roleViews(state: VillageState, player: Player, live?: AvatarCues): RoleView[] {
  const tl = player.timeline;
  const t = player.time;
  const current = tl.slots[state.index];
  return ROLES.map(({ id }) => {
    const cue = live?.[id];
    if (live) {
      if (cue?.status === "working") return { role: id, kind: "working", line: cue.text ?? null, since: null };
      if (cue?.status === "waiting" && current?.beat === state.beat && state.gate?.actionId === cue.actionId) {
        return { role: id, kind: "need", line: cue.text ?? null, since: null };
      }
      return { role: id, kind: null, line: null, since: null };
    }
    // The player can load a new source before React commits the state folded from that source.
    if (!current || current.beat !== state.beat) return { role: id, kind: null, line: null, since: 0 };
    const r = state.roles[id];
    if (r.status === "waiting") return { role: id, kind: "need", line: r.bubble, since: 0 };
    if (r.status === "working") {
      // the clock runs from the first of the role's beats in a row on this case
      let i = state.index;
      while (i > 0 && tl.slots[i - 1].beat.role === id && tl.slots[i - 1].beat.caseId === current.beat.caseId) i--;
      return { role: id, kind: "working", line: r.bubble, since: tl.slots[i]?.start ?? t };
    }
    if (r.status === "done" && r.beats > 0) {
      let end = -1;
      for (let i = state.index; i >= 0; i--) {
        const s = tl.slots[i];
        if (s.beat.role === id) {
          end = s.start + s.length;
          break;
        }
      }
      if (end >= 0 && t - end < 7) return { role: id, kind: "finished", line: r.bubble, since: 0 };
    }
    return { role: id, kind: null, line: null, since: 0 };
  });
}

export function Bubbles({ views, anchors, player, onNeed, onSelect, selected }: { views: RoleView[]; anchors: Map<string, HTMLElement>; player: Player; onNeed: () => void; onSelect: (r: RoleId) => void; selected: RoleId | null }) {
  return (
    <div className="vl-pins" aria-live="polite">
      {views.map((v) => (
        <Bubble key={v.role} view={v} anchors={anchors} player={player} onNeed={onNeed} onSelect={onSelect} selected={selected === v.role} />
      ))}
    </div>
  );
}

/**
 * Holds a bubble that just cleared for the length of its exit, so it fades out instead of vanishing.
 * Returns the view to draw and whether it is on its way out.
 */
function useLinger(view: RoleView, ms = 280): [RoleView, boolean] {
  const [held, setHeld] = useState<RoleView | null>(null);
  const last = useRef<RoleView>(view);
  useEffect(() => {
    if (view.kind) {
      setHeld(null);
      return;
    }
    const prev = last.current;
    if (!prev.kind) return;
    last.current = view;
    setHeld(prev);
    const timer = window.setTimeout(() => setHeld(null), ms);
    return () => window.clearTimeout(timer);
  }, [view.kind, ms]);
  useEffect(() => {
    if (view.kind) last.current = view;
  }, [view]);
  return held && !view.kind ? [held, true] : [view, false];
}

function Bubble({ view: live, anchors, player, onNeed, onSelect, selected }: { view: RoleView; anchors: Map<string, HTMLElement>; player: Player; onNeed: () => void; onSelect: (r: RoleId) => void; selected: boolean }) {
  const [view, leaving] = useLinger(live);
  const persona = PERSONAS[view.role];
  const ref = useAnchor(anchors, `bubble:${view.role}`);
  let big: ReactNode = null;
  if (view.kind === "working")
    big = (
      <span key="working" className="vl-bubble working">
        Working {view.since !== null && <Clock player={player} since={view.since} />}
      </span>
    );
  if (view.kind === "need")
    big = (
      <button key="need" className="vl-bubble need" onClick={onNeed} disabled={leaving} aria-label={`${agentName(view.role)} needs you: open the approval`}>
        Needs you
        <span className="vl-bang" aria-hidden="true">
          !
        </span>
      </button>
    );
  if (view.kind === "finished")
    big = (
      <span key="finished" className="vl-bubble finished">
        <span aria-hidden="true">✓</span> Finished
      </span>
    );
  return (
    <div ref={ref} className={`vl-pin vl-pin-role${view.kind ? ` on ${view.kind}` : ""}${leaving ? " leaving" : ""}${selected ? " selected" : ""}`} style={{ ["--role" as string]: persona.glow }}>
      <div className="vl-pin-inner">
        {big}
        {view.line && view.kind && (
          <span key={view.line} className="vl-line">
            {view.line}
          </span>
        )}
        <button className="vl-plate" onClick={() => onSelect(view.role)} title={`${persona.title}: open the tool log`} data-no-pick>
          <b>{agentName(view.role)}</b>
          <span>{persona.title}</span>
        </button>
      </div>
    </div>
  );
}

/** The tag that floats over the case file while it travels or lies on a desk. */
export function FileTag({ anchors, caseId, waiting }: { anchors: Map<string, HTMLElement>; caseId: string | null; waiting: boolean }) {
  const ref = useAnchor(anchors, "file");
  return (
    <div ref={ref} className={`vl-pin vl-pin-file${waiting ? " waiting" : ""}`} aria-hidden={!caseId}>
      {caseId && (
        <span key={caseId} className="vl-file">
          {caseId}
        </span>
      )}
    </div>
  );
}

const OUTCOME: Record<Outcome, { label: string; tone: string }> = {
  ok: { label: "ok", tone: "ok" },
  kept: { label: "holds", tone: "ok" },
  refuted: { label: "ruled out", tone: "out" },
  alarm: { label: "alarm", tone: "alarm" },
  info: { label: "info", tone: "info" },
  wait: { label: "waiting", tone: "wait" },
  denied: { label: "denied", tone: "out" },
};

export function RolePanel({ role, state, cue = IDLE_AVATAR, onClose }: { role: RoleId; state: VillageState; cue?: AvatarCue; onClose: () => void }) {
  const persona = PERSONAS[role];
  const r = state.roles[role];
  const log = [...r.log].reverse();
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  const { status } = cue;
  return (
    <aside className="vl-panel" aria-label={`${persona.title} tool log`} style={{ ["--role" as string]: persona.glow }} data-no-pick>
      <header>
        <AgentAvatar role={role} size={64} status={status} motionKey={cue.key} />
        <div className="vl-panel-id">
          <span className="vl-kicker">// {persona.title}</span>
          <h2>{agentName(role)}</h2>
          <p className="vl-meaning">{persona.names[0].meaning}</p>
        </div>
        <button className="vl-x" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </header>
      <p className="vl-job">{ROLE[role].job}</p>
      <div className={`vl-now ${status}`}>
        <span>{status === "working" ? "Now" : status === "waiting" ? "Needs you" : status === "sleeping" ? "Resting" : r.beats ? "Last" : "Idle"}</span>
        <b>{cue.text ?? r.bubble}</b>
      </div>
      <h3>
        Tool log <small>{r.log.length ? `${r.log.length} entr${r.log.length === 1 ? "y" : "ies"}, newest first` : ""}</small>
      </h3>
      {log.length === 0 ? (
        <p className="vl-empty">Nothing yet in this run. {persona.personality}</p>
      ) : (
        <ol className="vl-log">
          {log.map((e) => (
            <LogRow key={e.key} entry={e} />
          ))}
        </ol>
      )}
    </aside>
  );
}

function LogRow({ entry }: { entry: LogEntry }) {
  const o = OUTCOME[entry.outcome];
  return (
    <li className={`vl-entry ${o.tone}`}>
      <div className="vl-entry-head">
        <span className="vl-time">{hhmm(entry.simTs)}</span>
        <code>{entry.tool}</code>
        <span className={`vl-chip ${o.tone}`}>{o.label}</span>
      </div>
      <b>{entry.title}</b>
      {entry.hypothesis && <p className="vl-hyp">{entry.hypothesis}</p>}
      {entry.detail && <p>{entry.detail}</p>}
      {(entry.receipts.length > 0 || entry.agentReceipts?.length) ? (
        <div className="vl-receipts">
          {entry.agentReceipts?.length
            ? <AgentReceiptChips links={entry.agentReceipts} max={6} />
            : entry.linkedReceipts
              ? <ReceiptChips ids={entry.receipts} max={6} />
              : <span>{entry.receipts.length} evidence {entry.receipts.length === 1 ? "query" : "queries"}</span>}
        </div>
      ) : null}
    </li>
  );
}

export function ApprovalCard({
  gate,
  live,
  busy,
  error,
  onDecide,
  onClose,
}: {
  gate: NonNullable<VillageState["gate"]>;
  live: boolean;
  busy: boolean;
  error: string | null;
  onDecide: (d: "approve" | "deny") => void;
  onClose: () => void;
}) {
  const p = gate.proposal;
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="vl-scrim" role="dialog" aria-modal="true" aria-label="Approval" data-no-pick onClick={onClose}>
      <section className="vl-approval" onClick={(e) => e.stopPropagation()}>
        <header>
          <AgentAvatar role="operator" size={68} status="waiting" />
          <div>
            <span className="vl-kicker">// {agentName("operator")} needs you</span>
            <h2>Approve this action?</h2>
          </div>
        </header>
        <p className="vl-action">{gate.action}</p>
        {p ? (
          <dl className="vl-terms">
            <div>
              <dt>Scope</dt>
              <dd>
                {Object.entries(p.scope)
                  .map(([k, v]) => `${k} ${v.join(", ")}`)
                  .join(" · ") || "whole shop"}
              </dd>
            </div>
            <div>
              <dt>Success</dt>
              <dd>{p.success_rule.rule}</dd>
            </div>
            <div>
              <dt>Valid until</dt>
              <dd>{hhmm(p.expires_at)}</dd>
            </div>
          </dl>
        ) : null}
        {!live && (
          <p className="vl-note">
            Your decision applies to this historical investigation.
          </p>
        )}
        {error && <p className="vl-error">{error}</p>}
        <div className="vl-buttons">
          <button className="vl-btn deny" disabled={busy} onClick={() => onDecide("deny")}>
            Deny
          </button>
          <button className="vl-btn approve" disabled={busy} onClick={() => onDecide("approve")}>
            Approve
          </button>
        </div>
      </section>
    </div>
  );
}

/** One line at the bottom: who is doing what right now. */
export function Caption({ state, avatars }: { state: VillageState; avatars: AvatarCues }) {
  const beat = state.beat;
  if (!beat) return null;
  const r = state.roles[beat.role];
  const cue = avatars[beat.role] ?? IDLE_AVATAR;
  return (
    <div key={beat.key} className="vl-caption" style={{ ["--role" as string]: PERSONAS[beat.role].glow }}>
      <AgentAvatar role={beat.role} size={30} status={cue.status} motionKey={cue.key} badge={false} />
      <b>{agentName(beat.role)}</b>
      <span>{r.bubble}</span>
    </div>
  );
}
