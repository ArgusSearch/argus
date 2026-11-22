// Paints one agent avatar into a 2D canvas: the plush body from bot-avatars (MIT, drawn by its own engine) and
// our own armor around it, in the body's own space so every piece follows the hops, squashes and turns.
// Layers, back to front: the far half of the HUD ring, the body, the collar plate with its glowing seam and
// shoulder fins, the visor band over the eyes, the near half of the ring, the job's holo detail.

import {
  BotAvatarSim,
  botAvatarParts,
  botAvatarPresets,
  botAvatarShapes,
  drawBotAvatarFrame,
  type BotAvatarDrawConfig,
  type BotAvatarState,
} from "bot-avatars";
import { defaultLook, type CostumeKit, type Look } from "./costumes";
import type { Persona } from "./personas";
import { WORK_CUE_MS, type AvatarCue, type AvatarStatus } from "./state";

export type { AvatarStatus } from "./state";

/** The canvas is this many times the body box, as bot-avatars draws it (room for hops and fur). */
export const OVERSCAN = 1.5;
/** bot-avatars lifts the body this share of the box above the canvas center. */
const RISE = 0.1;

const STATE: Record<AvatarStatus, BotAvatarState> = { idle: "default", working: "default", waiting: "default", done: "default", sleeping: "sleeping" };

const FUR = { length: 1, density: 1.6, fuzz: 0.9, clumps: 0.4, curl: 0.7, gravity: 0.9 };

/** The top of the body at the face column (0..100 box). */
function topAt(path: Path2D, u: number): number {
  const probe = document.createElement("canvas").getContext("2d");
  if (!probe) return 15;
  for (let v = 0; v <= 100; v += 0.5) if (probe.isPointInPath(path, u, v)) return v;
  return 15;
}

/** Half the body's width at height v (0..100 box), measured once from its outline. */
function halfWidthAt(path: Path2D, v: number, fallback = 30): number {
  const probe = document.createElement("canvas").getContext("2d");
  if (!probe) return 30;
  let w = 0;
  for (let u = 50; u <= 100; u += 0.5) {
    if (probe.isPointInPath(path, u, v)) w = u - 50;
  }
  return w || fallback;
}

function rgba(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

export class AvatarPainter {
  readonly persona: Persona;
  readonly sim: BotAvatarSim;
  private readonly cfg: BotAvatarDrawConfig;
  private readonly body: HTMLCanvasElement;
  private readonly ringHalf: number;
  private readonly fx: number;
  private readonly fy: number;
  private readonly fs: number;
  private status: AvatarStatus = "idle";
  private cueKey: AvatarCue["key"];
  private cueAge = 0;
  private time = 0;
  /** the role costume, or null for the plain armored bot */
  readonly look: Look | null;
  private readonly top: number;
  private readonly halves = new Map<number, number>();
  private readonly path: Path2D;
  /** the costume's own layer, made on first paint */
  private layer: HTMLCanvasElement | null = null;

  /** `look`: the costume to wear; by default the role's default look (look 1), `null` for the plain armored bot. */
  constructor(persona: Persona, seed: number, still = false, look?: Look | null) {
    this.persona = persona;
    this.look = look === undefined ? defaultLook(persona.role) : look;
    const preset = botAvatarPresets[persona.body];
    const path = new Path2D(botAvatarShapes[persona.body]);
    this.path = path;
    this.top = topAt(path, preset.faceX) - 50;
    const parts = botAvatarParts[persona.body];
    this.fx = preset.faceX - 50;
    this.fy = preset.faceY - 50;
    this.fs = preset.faceScale;
    this.ringHalf = Math.max(halfWidthAt(path, 50), halfWidthAt(path, 70)) + 11;
    this.cfg = {
      path,
      face: preset.face,
      faceX: preset.faceX,
      faceY: preset.faceY,
      faceScale: preset.faceScale,
      color: persona.fur,
      ink: "#141a2b",
      shading: "fabric",
      shadow: 1.15,
      highlight: 1.45,
      rim: 0.7,
      spread: 1.6,
      light: 295,
      roundness: 1,
      fur: FUR,
      vivid: 0,
      lightFront: 32,
      backSoftness: 1,
      typeKey: `argus:${persona.body}`,
      still,
      furOnIdle: true,
      parts: parts ? new Path2D(parts) : undefined,
    };
    this.sim = new BotAvatarSim(seed, "default");
    this.sim.setTurn(0.55);
    this.body = document.createElement("canvas");
  }

  setStatus(status: AvatarStatus, key?: AvatarCue["key"]): void {
    if (status === this.status && key === this.cueKey) return;
    this.status = status;
    this.cueKey = key;
    this.cueAge = 0;
    this.sim.setState(STATE[status]);
  }

  get moving(): boolean {
    return this.status === "working" && this.cueAge < WORK_CUE_MS / 1000;
  }

  /** Advances the body's motion by dt seconds (0 keeps the pose) and paints the whole avatar. */
  paint(ctx: CanvasRenderingContext2D, box: number, dpr: number, dt: number, approval = false): void {
    this.time += dt;
    this.cueAge = Math.min(WORK_CUE_MS / 1000, this.cueAge + dt);
    if (dt > 0) this.sim.update(dt);
    const a = box * OVERSCAN;
    const size = Math.max(1, Math.round(a * dpr));
    if (this.body.width !== size) {
      this.body.width = size;
      this.body.height = size;
    }
    const bctx = this.body.getContext("2d");
    if (!bctx) return;
    bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.cfg.dpr = dpr;
    drawBotAvatarFrame(bctx, box, this.sim.pose, this.cfg);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.clearRect(0, 0, a, a);
    const pose = this.sim.pose;
    const e = box / 100;
    const F = Math.cos(pose.roll);
    const W = Math.sin(pose.roll);
    const T = 50 * (1 - pose.sy) * e;
    const ox = a / 2 + pose.x * e - W * T;
    const oy = a / 2 + RISE * box + pose.y * e + F * T;
    const C = pose.sx * e;
    const S = pose.sy * e;
    const small = box < 44;

    // body space: (0, 0) is the body's center, 100 units across
    ctx.save();
    ctx.transform(F * C, W * C, -W * S, F * S, ox, oy);
    if (!small) this.ring(ctx, true);
    ctx.restore();

    ctx.drawImage(this.body, 0, 0, a, a);

    ctx.save();
    ctx.transform(F * C, W * C, -W * S, F * S, ox, oy);
    const facing = Math.cos(pose.yaw) * Math.cos(pose.pitch);
    if (facing > 0.15) {
      ctx.globalAlpha = Math.min(1, (facing - 0.15) / 0.3);
      this.visor(ctx, pose.yaw, pose.pitch, small);
      this.helmet(ctx, pose.yaw, pose.pitch, small);
      ctx.globalAlpha = 1;
    }
    if (!small) {
      this.ring(ctx, false);
      if (!this.look) this.detail(ctx);
    }
    ctx.restore();
    if (this.look) this.costume(ctx, this.look, a, size, dpr, [F * C, W * C, -W * S, F * S, ox, oy], pose.yaw, pose.pitch, small);
    if (approval) {
      const x = a * 0.76;
      const y = a * 0.28;
      const radius = box * (0.1 + 0.014 * Math.sin(this.time * 4.5));
      ctx.fillStyle = "#e5534b";
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.fillRect(x - box * 0.009, y - radius * 0.55, box * 0.018, radius * 0.7);
      ctx.fillRect(x - box * 0.009, y + radius * 0.31, box * 0.018, box * 0.018);
    }
  }

  /**
   * The costume on a layer of its own, then onto the avatar with one soft shadow: hats and props stand off the
   * body, and a frame pays for one blur instead of one per curl and prop.
   */
  private costume(
    ctx: CanvasRenderingContext2D,
    look: Look,
    a: number,
    size: number,
    dpr: number,
    m: [number, number, number, number, number, number],
    yaw: number,
    pitch: number,
    small: boolean,
  ): void {
    this.layer ??= document.createElement("canvas");
    const layer = this.layer;
    if (layer.width !== size) {
      layer.width = size;
      layer.height = size;
    }
    const lctx = layer.getContext("2d");
    if (!lctx) return;
    lctx.setTransform(1, 0, 0, 1, 0, 0);
    lctx.clearRect(0, 0, size, size);
    lctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    lctx.transform(...m);
    look.draw(this.kit(lctx, yaw, pitch, small));
    ctx.save();
    ctx.shadowColor = "rgba(11,19,32,0.32)";
    ctx.shadowBlur = 3 * dpr;
    ctx.shadowOffsetY = 1.4 * dpr;
    ctx.drawImage(layer, 0, 0, a, a);
    ctx.restore();
  }

  private kit(ctx: CanvasRenderingContext2D, yaw: number, pitch: number, small: boolean): CostumeKit {
    return {
      ctx,
      top: this.top,
      half: (y: number) => {
        const v = Math.round(y + 50);
        let h = this.halves.get(v);
        if (h === undefined) {
          h = halfWidthAt(this.path, Math.max(1, Math.min(99, v)), 0);
          this.halves.set(v, h);
        }
        return h;
      },
      fx: this.fx,
      fy: this.fy,
      fs: this.fs,
      fur: this.persona.fur,
      glow: this.persona.glow,
      time: this.moving ? this.cueAge : 0,
      busy: this.status === "working",
      workTime: this.moving ? this.cueAge : 0,
      face: (x: number, y: number) => this.project(x, y, yaw, pitch),
      yaw,
      small,
    };
  }

  /**
   * A point of the face, (x, y) in face units around the face center, on the head sphere bot-avatars draws the
   * eyes on (radius 30, turned by yaw and pitch), in body units. Null when it is round the back.
   */
  private project(x: number, y: number, yaw: number, pitch: number): [number, number] | null {
    const R = 30;
    const a = Math.asin(Math.max(-1, Math.min(1, x / R))) + yaw;
    const e = Math.asin(Math.max(-1, Math.min(1, -y / R))) + pitch;
    const z = Math.cos(a) * Math.cos(e);
    if (z <= 0.02) return null;
    return [this.fx + this.fs * R * Math.sin(a) * Math.cos(e), this.fy - this.fs * R * Math.sin(e)];
  }

  private line(xs: number[], y: (x: number) => number, yaw: number, pitch: number): [number, number][] {
    const out: [number, number][] = [];
    for (const x of xs) {
      const p = this.project(x, y(x), yaw, pitch);
      if (p) out.push(p);
    }
    return out;
  }

  private curve(ctx: CanvasRenderingContext2D, pts: [number, number][], move = true): void {
    pts.forEach(([x, y], i) => (i === 0 && move ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
  }

  /** Helmet pieces: temple modules with swept fins at the visor's ends and an emitter above its middle. */
  private helmet(ctx: CanvasRenderingContext2D, yaw: number, pitch: number, small: boolean): void {
    const p = this.persona;
    const metal = (x0: number, y0: number, r: number) => {
      const g = ctx.createRadialGradient(x0 - r * 0.35, y0 - r * 0.45, r * 0.1, x0, y0, r);
      g.addColorStop(0, "#ffffff");
      g.addColorStop(0.6, "#dfe6f0");
      g.addColorStop(1, "#97a4b8");
      return g;
    };
    for (const side of [-1, 1]) {
      const c = this.project(side * 25.5, 1, yaw, pitch);
      if (!c) continue;
      const tip = this.project(side * 29.8, -9, yaw, pitch) ?? [c[0] + side * 5, c[1] - 9];
      const base = this.project(side * 27.5, -3, yaw, pitch) ?? c;
      if (!small) {
        // the swept fin, from the temple up and out
        ctx.beginPath();
        ctx.moveTo(base[0] - side * 2.2, base[1]);
        ctx.quadraticCurveTo(tip[0] - side * 1.5, tip[1] + 6, tip[0] + side * 2.5, tip[1]);
        ctx.quadraticCurveTo(tip[0] + side * 1.8, tip[1] + 7, base[0] + side * 2.6, base[1] + 2);
        ctx.closePath();
        ctx.fillStyle = metal(tip[0], tip[1] + 6, 10);
        ctx.fill();
        ctx.lineWidth = 0.6;
        ctx.strokeStyle = rgba("#1b2436", 0.3);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(base[0] + side * 0.2, base[1] - 1);
        ctx.quadraticCurveTo(tip[0] - side * 0.2, tip[1] + 6, tip[0] + side * 1.6, tip[1] + 1.2);
        ctx.strokeStyle = p.glow;
        ctx.lineWidth = 0.8;
        ctx.shadowColor = p.glow;
        ctx.shadowBlur = 4;
        ctx.stroke();
        ctx.shadowBlur = 0;
      }
      // the temple module
      const r = small ? 5 : 4.6;
      ctx.beginPath();
      ctx.arc(c[0], c[1], r, 0, Math.PI * 2);
      ctx.fillStyle = metal(c[0], c[1], r);
      ctx.shadowColor = "rgba(11,19,32,0.3)";
      ctx.shadowBlur = 2;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.lineWidth = small ? 1.3 : 0.9;
      ctx.strokeStyle = p.glow;
      ctx.shadowColor = p.glow;
      ctx.shadowBlur = small ? 2 : 5;
      ctx.beginPath();
      ctx.arc(c[0], c[1], r * 0.58, 0, Math.PI * 2);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
    if (small || this.look) return;
    // the forehead emitter: a small hexagon of light on a bridge above the visor
    const e = this.project(0, -11.5, yaw, pitch);
    const b = this.project(0, -4.8, yaw, pitch);
    if (!e || !b) return;
    ctx.beginPath();
    ctx.moveTo(b[0] - 1.6, b[1]);
    ctx.lineTo(e[0] - 1.2, e[1]);
    ctx.lineTo(e[0] + 1.2, e[1]);
    ctx.lineTo(b[0] + 1.6, b[1]);
    ctx.closePath();
    ctx.fillStyle = "#dfe6f0";
    ctx.fill();
    const pulse = 0.75 + 0.25 * Math.sin(this.time * (this.status === "working" ? 6 : 2));
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2 + Math.PI / 6;
      const x = e[0] + Math.cos(a) * 3.6;
      const y = e[1] + Math.sin(a) * 3.6;
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = metal(e[0], e[1], 4);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(e[0], e[1], 1.9, 0, Math.PI * 2);
    ctx.fillStyle = rgba(p.glow, pulse);
    ctx.shadowColor = p.glow;
    ctx.shadowBlur = 7;
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  private visor(ctx: CanvasRenderingContext2D, yaw: number, pitch: number, small: boolean): void {
    const p = this.persona;
    const w = 23;
    const h = 5.6;
    const y0 = 1;
    const n = 14;
    const xs = Array.from({ length: n + 1 }, (_, i) => -w + (2 * w * i) / n);
    const top = this.line(xs, (x) => y0 - h + 1.2 * (x / w) ** 2, yaw, pitch);
    const bottom = this.line(xs, (x) => y0 + h - 0.6 * (x / w) ** 2, yaw, pitch);
    if (top.length < 4 || bottom.length < 4) return;
    ctx.beginPath();
    this.curve(ctx, top);
    this.curve(ctx, [...bottom].reverse(), false);
    ctx.closePath();
    const y1 = top[top.length >> 1][1];
    const y2 = bottom[bottom.length >> 1][1];
    const g = ctx.createLinearGradient(0, y1, 0, y2);
    g.addColorStop(0, "rgba(240,248,255,0.42)");
    g.addColorStop(0.55, rgba(p.glow, 0.1));
    g.addColorStop(1, rgba(p.glow, 0.26));
    ctx.fillStyle = g;
    ctx.fill();
    ctx.lineWidth = small ? 1.3 : 0.85;
    ctx.strokeStyle = "rgba(255,255,255,0.95)";
    ctx.beginPath();
    this.curve(ctx, top);
    ctx.stroke();
    ctx.strokeStyle = p.glow;
    ctx.shadowColor = p.glow;
    ctx.shadowBlur = small ? 2 : 5;
    ctx.beginPath();
    this.curve(ctx, bottom);
    ctx.stroke();
    ctx.shadowBlur = 0;
    // the visor's temple pieces, where they face us
    ctx.fillStyle = "#dfe6f0";
    for (const x of [-w, w]) {
      const a = this.project(x, y0 - h, yaw, pitch);
      const b = this.project(x, y0 + h, yaw, pitch);
      if (!a || !b) continue;
      ctx.beginPath();
      ctx.ellipse(a[0], (a[1] + b[1]) / 2, 2.2, (b[1] - a[1]) / 2 + 1.2, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    if (small) return;
    // HUD ticks along the lower rim
    ctx.strokeStyle = rgba(p.glow, 0.9);
    ctx.lineWidth = 0.55;
    for (let i = 2; i <= n - 2; i += 2) {
      const a = this.project(xs[i], y0 + h - 1.4, yaw, pitch);
      const b = this.project(xs[i], y0 + h - (i % 4 === 0 ? 3.4 : 2.3), yaw, pitch);
      if (!a || !b) continue;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.stroke();
    }
    // the light that runs along the visor: a slow glint, a fast sweep for the watcher's scan
    const scan = p.detail === "scan" && this.moving;
    const sx = Math.sin(this.time * (scan ? 2.1 : 0.7)) * w * 0.9;
    const s = this.project(sx, y0, yaw, pitch);
    if (s) {
      const r = scan ? 8 : 4.5;
      const grad = ctx.createRadialGradient(s[0], s[1], 0, s[0], s[1], r);
      grad.addColorStop(0, "rgba(255,255,255,0.9)");
      grad.addColorStop(0.35, rgba(p.glow, 0.55));
      grad.addColorStop(1, rgba(p.glow, 0));
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(s[0], s[1], r, 0, Math.PI * 2);
      ctx.fill();
    }
    if (p.detail === "reticle") {
      // a targeting reticle round the right eye
      const c = this.project(12.5, y0, yaw, pitch);
      if (c) {
        const r = 7 * this.fs;
        ctx.strokeStyle = "#ffffff";
        ctx.shadowColor = p.glow;
        ctx.shadowBlur = 5;
        ctx.lineWidth = 0.75;
        ctx.beginPath();
        ctx.arc(c[0], c[1], r, 0, Math.PI * 2);
        ctx.stroke();
        const spin = this.time * 0.8;
        for (let q = 0; q < 4; q++) {
          const ang = spin + (q * Math.PI) / 2;
          ctx.beginPath();
          ctx.moveTo(c[0] + Math.cos(ang) * (r + 1), c[1] + Math.sin(ang) * (r + 1));
          ctx.lineTo(c[0] + Math.cos(ang) * (r + 3.2), c[1] + Math.sin(ang) * (r + 3.2));
          ctx.stroke();
        }
        ctx.shadowBlur = 0;
      }
    }
  }

  /** The holo ring around the waist: far half behind the body, near half in front. */
  private ring(ctx: CanvasRenderingContext2D, far: boolean): void {
    const p = this.persona;
    const rx = this.ringHalf;
    const ry = rx * 0.2;
    const cy = 30;
    const busy = this.status === "working";
    const t = busy ? this.cueAge * 1.4 : 0;
    ctx.save();
    ctx.strokeStyle = rgba(p.glow, far ? 0.45 : 0.85);
    ctx.shadowColor = p.glow;
    ctx.shadowBlur = far ? 0 : 6;
    ctx.lineWidth = 1;
    ctx.setLineDash([7, 3.5, 1.5, 3.5]);
    ctx.lineDashOffset = -t * 12;
    ctx.beginPath();
    ctx.ellipse(0, cy, rx, ry, 0, far ? Math.PI : 0, far ? Math.PI * 2 : Math.PI);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.lineWidth = 0.5;
    ctx.strokeStyle = rgba(p.glow, far ? 0.25 : 0.5);
    ctx.beginPath();
    ctx.ellipse(0, cy, rx + 4, ry + 1.2, 0, far ? Math.PI : 0, far ? Math.PI * 2 : Math.PI);
    ctx.stroke();
    // a blip running round
    const ang = t % (Math.PI * 2);
    const inFront = Math.sin(ang) > 0;
    if (inFront !== far) {
      ctx.fillStyle = "#ffffff";
      ctx.shadowBlur = 8;
      ctx.beginPath();
      ctx.arc(Math.cos(ang) * rx, cy + Math.sin(ang) * ry, 1.7, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  /** The job's floating holo icon, beside the head. */
  private detail(ctx: CanvasRenderingContext2D): void {
    const p = this.persona;
    const t = this.time;
    const x = this.ringHalf - 4;
    const y = -38 + Math.sin(t * 1.3) * 2;
    ctx.save();
    ctx.translate(x, y);
    ctx.strokeStyle = p.glow;
    ctx.fillStyle = rgba(p.glow, 0.22);
    ctx.lineWidth = 1;
    ctx.shadowColor = p.glow;
    ctx.shadowBlur = 6;
    const plate = (w: number, h: number) => {
      ctx.beginPath();
      ctx.roundRect(-w / 2, -h / 2, w, h, 2.5);
      ctx.fill();
      ctx.stroke();
    };
    switch (p.detail) {
      case "scan": {
        plate(18, 14);
        ctx.beginPath();
        ctx.arc(0, 4, 8, Math.PI * 1.15, Math.PI * 1.85);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(0, 4, 4.5, Math.PI * 1.15, Math.PI * 1.85);
        ctx.stroke();
        const a = Math.PI * 1.15 + ((Math.sin(t * 2.1) + 1) / 2) * Math.PI * 0.7;
        ctx.beginPath();
        ctx.moveTo(0, 4);
        ctx.lineTo(Math.cos(a) * 8, 4 + Math.sin(a) * 8);
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();
        break;
      }
      case "reticle": {
        plate(18, 14);
        ctx.beginPath();
        ctx.arc(-1.5, -1, 4, 0, Math.PI * 2);
        ctx.moveTo(1.5, 2);
        ctx.lineTo(5.5, 5.5);
        ctx.stroke();
        break;
      }
      case "scale": {
        plate(20, 15);
        const tilt = Math.sin(t * 1.1) * 0.25;
        ctx.beginPath();
        ctx.moveTo(0, -5);
        ctx.lineTo(0, 5);
        ctx.moveTo(-4, 5.5);
        ctx.lineTo(4, 5.5);
        ctx.stroke();
        ctx.save();
        ctx.translate(0, -4);
        ctx.rotate(tilt);
        ctx.beginPath();
        ctx.moveTo(-7, 0);
        ctx.lineTo(7, 0);
        ctx.stroke();
        for (const s of [-1, 1]) {
          ctx.beginPath();
          ctx.moveTo(s * 7, 0);
          ctx.lineTo(s * 7 - 2.5, 4);
          ctx.lineTo(s * 7 + 2.5, 4);
          ctx.closePath();
          ctx.stroke();
        }
        ctx.restore();
        break;
      }
      case "bars": {
        plate(20, 15);
        for (let i = 0; i < 4; i++) {
          const h = 3 + (Math.sin(t * 2 + i * 1.3) + 1) * 2.6;
          ctx.fillStyle = i === 2 ? "#ffffff" : p.glow;
          ctx.fillRect(-7 + i * 4, 5 - h, 2.4, h);
        }
        break;
      }
      case "page": {
        plate(15, 18);
        const lines = 1 + Math.floor((t * 1.5) % 5);
        ctx.fillStyle = "#ffffff";
        for (let i = 0; i < lines; i++) ctx.fillRect(-4.5, -5.5 + i * 2.8, i === lines - 1 ? 5 : 9, 1);
        break;
      }
      case "power": {
        plate(17, 17);
        ctx.strokeStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(0, 0.8, 4.5, -Math.PI * 0.32, Math.PI * 1.32);
        ctx.moveTo(0, -5);
        ctx.lineTo(0, 0.5);
        ctx.stroke();
        break;
      }
      case "graph": {
        plate(20, 16);
        const pts: [number, number][] = [
          [-6, -3],
          [0, -5],
          [6, -1],
          [-2, 4],
          [5, 5],
        ];
        const spin = Math.sin(t * 0.9) * 0.15;
        ctx.rotate(spin);
        ctx.beginPath();
        for (const [a, b] of [
          [0, 1],
          [1, 2],
          [0, 3],
          [3, 4],
          [2, 4],
        ]) {
          ctx.moveTo(pts[a][0], pts[a][1]);
          ctx.lineTo(pts[b][0], pts[b][1]);
        }
        ctx.stroke();
        ctx.fillStyle = "#ffffff";
        for (const [px, py] of pts) {
          ctx.beginPath();
          ctx.arc(px, py, 1.3, 0, Math.PI * 2);
          ctx.fill();
        }
        break;
      }
    }
    ctx.restore();
  }
}
