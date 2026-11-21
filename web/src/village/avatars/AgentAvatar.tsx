// <AgentAvatar role status size nameplate />: one of the seven Argus agents, animated. Every avatar on a page
// shares one animation frame loop; an avatar that is off screen or in a hidden tab does not paint.
//
//   import { AgentAvatar } from "../village/avatars";
//   <AgentAvatar role="operator" status="waiting" size={64} nameplate />
//
// status: idle (looks around), working (busy hop), waiting (needs you: coral badge), done (green check),
// sleeping. With prefers-reduced-motion the still pose is painted once per change.

import { useEffect, useRef } from "react";
import type { RoleId } from "../roles";
import { AvatarPainter, OVERSCAN, type AvatarStatus } from "./painter";
import { agentName, PERSONAS } from "./personas";
import "./avatars.css";

export interface AgentAvatarProps {
  role: RoleId;
  /** what the agent is doing; default idle */
  status?: AvatarStatus;
  /** body size in CSS px (the canvas is 1.5 times this, for hops and the HUD ring); default 64 */
  size?: number;
  /** show the acronym and the job title under the avatar */
  nameplate?: boolean;
  /** show the status badge (needs you, finished) at the top right; default true */
  badge?: boolean;
  /** freeze the motion (screenshots, print) */
  paused?: boolean;
  className?: string;
}

interface Entry {
  canvas: HTMLCanvasElement;
  painter: AvatarPainter;
  box: number;
  visible: boolean;
  paused: boolean;
  dirty: boolean;
}

const entries = new Set<Entry>();
let frame = 0;
let last = 0;
const calm = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function tick(now: number) {
  frame = 0;
  const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
  last = now;
  const still = calm() || document.hidden;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  let live = false;
  for (const e of entries) {
    if (!e.visible) continue;
    const moving = !e.paused && !still;
    if (!moving && !e.dirty) continue;
    const ctx = e.canvas.getContext("2d");
    if (!ctx) continue;
    const px = Math.round(e.box * OVERSCAN * dpr);
    if (e.canvas.width !== px) {
      e.canvas.width = px;
      e.canvas.height = px;
    }
    e.painter.paint(ctx, e.box, dpr, moving ? dt : 0);
    e.dirty = false;
    if (moving) live = true;
  }
  if (live || [...entries].some((e) => e.dirty && e.visible)) schedule();
  else last = 0;
}

function schedule() {
  if (!frame && typeof requestAnimationFrame !== "undefined") frame = requestAnimationFrame(tick);
}

let observer: IntersectionObserver | null = null;
const byCanvas = new WeakMap<Element, Entry>();

function watch(e: Entry) {
  if (typeof IntersectionObserver === "undefined") return;
  observer ??= new IntersectionObserver((items) => {
    for (const it of items) {
      const entry = byCanvas.get(it.target);
      if (!entry) continue;
      entry.visible = it.isIntersecting;
      entry.dirty = true;
    }
    schedule();
  });
  byCanvas.set(e.canvas, e);
  observer.observe(e.canvas);
}

let seedCounter = 0;

export function AgentAvatar({ role, status = "idle", size = 64, nameplate = false, badge = true, paused = false, className }: AgentAvatarProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  const entry = useRef<Entry | null>(null);
  const persona = PERSONAS[role];

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const e: Entry = {
      canvas,
      painter: new AvatarPainter(persona, ((seedCounter++ * 0.6180339) % 1) + 0.01, calm()),
      box: size,
      visible: true,
      paused,
      dirty: true,
    };
    entry.current = e;
    entries.add(e);
    watch(e);
    schedule();
    return () => {
      entries.delete(e);
      observer?.unobserve(canvas);
      entry.current = null;
    };
    // a new painter only for a new role; size, status and paused update in place
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  useEffect(() => {
    const e = entry.current;
    if (!e) return;
    e.box = size;
    e.paused = paused;
    e.painter.setStatus(status);
    e.dirty = true;
    schedule();
  }, [size, status, paused]);

  const name = agentName(role);
  const label = `${name}, the ${persona.title}${status === "idle" ? "" : `, ${status === "waiting" ? "needs you" : status}`}`;
  return (
    <span
      className={`agent-avatar ${className ?? ""}`}
      data-role={role}
      data-status={status}
      style={{ ["--av-size" as string]: `${size}px`, ["--av-glow" as string]: persona.glow }}
      role="img"
      aria-label={label}
    >
      <span className="agent-avatar-stage">
        <canvas ref={ref} aria-hidden="true" />
        {badge && status === "waiting" && <span className="agent-avatar-badge need">!</span>}
        {badge && status === "done" && <span className="agent-avatar-badge done">✓</span>}
      </span>
      {nameplate && (
        <span className="agent-avatar-plate">
          <b>{name}</b>
          <span>{persona.title}</span>
        </span>
      )}
    </span>
  );
}
