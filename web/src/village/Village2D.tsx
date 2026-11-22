// The 2D village: the same layout, bots, bubbles and case file without WebGL, for headless capture, a missing
// WebGL2, or ?village2d=1. Igloos are CSS domes cut open to a warm room with the live <AgentAvatar> inside;
// the case file walks between them on the same clock as the 3D stage.

import { useEffect, useRef, useState } from "react";
import { AgentAvatar } from "./avatars/AgentAvatar";
import { IDLE_AVATAR, type AvatarCues } from "./avatars/state";
import { measureKeepout, placePin } from "./Overlay";
import type { Player } from "./player";
import { APPROVAL_POST, ROLE, ROLES, type RoleId } from "./roles";
import { slotAt, TRAVEL, type VillageState } from "./timeline";

interface Box {
  w: number;
  h: number;
}

/** Ground (x, z) to stage pixels: a view from the front and above, like the 3D camera. */
function at(box: Box, x: number, z: number, y = 0): [number, number] {
  const s = Math.min(box.w / 30, box.h / 22.5);
  return [box.w / 2 + x * s, box.h * 0.56 + (z + 0.2) * s * 0.8 - y * s * 0.8];
}

const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

export function Village2D({ player, state, avatars, anchors, onSelect }: { player: Player; state: VillageState; avatars: AvatarCues; anchors: Map<string, HTMLElement>; onSelect: (r: RoleId) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const walker = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<Box>({ w: 1200, h: 700 });
  const [mover, setMover] = useState<RoleId | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    let frame = 0;
    const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const keepout = ref.current ? measureKeepout(ref.current) : null;
    const pin = (key: string, p: [number, number]) => {
      const el = anchors.get(key);
      if (el) placePin(el, p[0], p[1], true, keepout);
    };
    const loop = () => {
      frame = requestAnimationFrame(loop);
      const s = Math.min(box.w / 30, box.h / 22.5);
      for (const r of ROLES) {
        pin(`bubble:${r.id}`, at(box, r.x, r.z - 0.4, r.size * 1.25));
      }
      const tl = player.timeline;
      const t = player.time;
      const i = slotAt(tl, t);
      const slot = tl.slots[i];
      const file = anchors.get("file");
      let who: RoleId | null = null;
      if (state.gate && file) {
        pin("file", at(box, ...APPROVAL_POST, 1.3));
        file.style.opacity = "1";
      } else if (!calm && slot?.from && t - slot.start < TRAVEL) {
        const k = ease((t - slot.start) / TRAVEL);
        const a = ROLE[slot.from];
        const b = ROLE[slot.beat.role];
        const p = at(box, a.x + (b.x - a.x) * k, a.z + (b.z - a.z) * k + Math.sin(k * Math.PI) * 2.2, 0.2);
        // the gait, as in 3D: a bounce per step and a lean into the walk, easing in and out at the doors
        const local = t - slot.start;
        const gait = Math.max(0, Math.min(1, local / 0.3, (TRAVEL - local) / 0.3));
        const bob = Math.abs(Math.sin(local * 9.5)) * s * 0.28 * gait;
        const lean = Math.sign(b.x - a.x) * 7 * gait + Math.sin(local * 9.5) * 2.5 * gait;
        if (walker.current) walker.current.style.transform = `translate3d(${p[0] - s * 0.78}px, ${p[1] - s * 1.6 - bob}px, 0) rotate(${lean.toFixed(2)}deg)`;
        who = slot.from;
        pin("file", [p[0] + s * 0.2, p[1] - s * 0.6]);
        if (file) file.style.opacity = "1";
      } else if (state.beat?.caseId) {
        const r = ROLE[state.beat.role];
        pin("file", at(box, r.x - 0.8, r.z, 1.4));
        if (file) file.style.opacity = "1";
      } else if (file) file.style.opacity = "0";
      setMover((m) => (m === who ? m : who));
    };
    loop();
    return () => cancelAnimationFrame(frame);
  }, [box, player, anchors, state.beat, state.gate]);

  const s = Math.min(box.w / 30, box.h / 22.5);
  const plaza = at(box, 0, 0.2);
  return (
    <div ref={ref} className="vl-stage2d">
      <svg className="vl-paths" width={box.w} height={box.h} aria-hidden="true">
        <ellipse cx={plaza[0]} cy={plaza[1]} rx={s * 2.1} ry={s * 1.4} />
        {ROLES.map((r) => {
          const d = at(box, r.x, r.z + r.size * 0.7);
          return <line key={r.id} x1={d[0]} y1={d[1]} x2={plaza[0]} y2={plaza[1]} />;
        })}
      </svg>
      {ROLES.slice()
        .sort((a, b) => a.z - b.z)
        .map((r) => {
          const [x, y] = at(box, r.x, r.z);
          const w = r.size * s * 2.2;
          const rs = avatars[r.id] ?? IDLE_AVATAR;
          const busy = rs.status === "working";
          return (
            <button
              key={r.id}
              className={`vl-igloo2d${busy ? " busy" : ""}${rs.status === "waiting" ? " waiting" : ""}`}
              style={{ left: x - w / 2, top: y - w * 0.62, width: w, height: w * 0.62, ["--role" as string]: r.color }}
              onClick={() => onSelect(r.id)}
              aria-label={`${r.name} igloo`}
            >
              <span className="vl-dome" />
              <span className="vl-room" />
              <span className="vl-bot2d" style={{ opacity: mover === r.id ? 0.25 : 1 }}>
                <AgentAvatar role={r.id} size={Math.round(s * 1.55)} status={rs.status} motionKey={rs.key} badge={rs.status === "waiting"} />
              </span>
            </button>
          );
        })}
      <div ref={walker} className="vl-walker" aria-hidden="true" style={{ opacity: mover ? 1 : 0 }}>
        {mover && <AgentAvatar role={mover} size={Math.round(s * 1.55)} paused badge={false} />}
      </div>
    </div>
  );
}
