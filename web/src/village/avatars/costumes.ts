// Role costumes over the plush bots: an instantly readable silhouette per job (the lighthouse keeper's rain hat
// and lantern, the detective's trench coat and fedora, the butler's bow tie and silver tray...). Two looks per
// role; the painter draws the chosen one in the body's own space after the armor, so hats and props follow the
// hops and the squash. Vector shapes only, our own designs. Looks draw without shadows: the painter lays the
// whole costume on its own layer and gives it one soft shadow, so a frame pays for one blur, not one per curl.

import type { RoleId } from "../roles";

export type LookId = 1 | 2;

export interface CostumeKit {
  ctx: CanvasRenderingContext2D;
  /** the head's top at the face column, body units (y down, 0 = body centre) */
  top: number;
  /** half the body's width at height y (body units) */
  half: (y: number) => number;
  fx: number;
  fy: number;
  fs: number;
  fur: string;
  glow: string;
  time: number;
  busy: boolean;
  workTime: number;
  /** a face point (face units) on the head sphere, in body units, or null round the back */
  face: (x: number, y: number) => [number, number] | null;
  yaw: number;
  small: boolean;
}

export interface Look {
  id: LookId;
  name: string;
  /** what makes it readable, in a few words, for the board */
  reads: string;
  draw: (k: CostumeKit) => void;
}

// ---------------------------------------------------------------- drawing helpers

function shade(ctx: CanvasRenderingContext2D, x: number, y0: number, y1: number, top: string, bottom: string) {
  const g = ctx.createLinearGradient(x, y0, x, y1);
  g.addColorStop(0, top);
  g.addColorStop(1, bottom);
  return g;
}

function outline(ctx: CanvasRenderingContext2D, w = 0.7, a = 0.35) {
  ctx.lineWidth = w;
  ctx.strokeStyle = `rgba(20,24,36,${a})`;
  ctx.stroke();
}

/** A little plush mitten that holds a prop. */
function mitten(k: CostumeKit, x: number, y: number, r = 6) {
  const { ctx } = k;
  const g = ctx.createRadialGradient(x - r * 0.35, y - r * 0.4, r * 0.15, x, y, r);
  g.addColorStop(0, "#ffffff");
  g.addColorStop(0.35, k.fur);
  g.addColorStop(1, darken(k.fur, 0.35));
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = g;
  ctx.fill();
}

function darken(hex: string, k: number): string {
  const n = parseInt(hex.slice(1), 16);
  const f = (c: number) => Math.round(c * (1 - k));
  return `rgb(${f((n >> 16) & 255)},${f((n >> 8) & 255)},${f(n & 255)})`;
}

/** The head's x at the top, shifted with the turn. */
function headX(k: CostumeKit) {
  return k.fx + Math.sin(k.yaw) * 9;
}

function brimHat(k: CostumeKit, o: { crown: string; band: string; brim: string; w: number; h: number; tilt?: number; dent?: boolean; up?: number }) {
  const { ctx } = k;
  const x = headX(k);
  const y = k.top + (o.up ?? 5);
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(o.tilt ?? -0.08);
  // brim
  ctx.beginPath();
  ctx.ellipse(0, 0, o.w, o.w * 0.24, 0, 0, Math.PI * 2);
  ctx.fillStyle = shade(ctx, 0, -6, 6, o.brim, darken(o.brim, 0.3));
  ctx.fill();
  outline(ctx);
  // crown
  const cw = o.w * 0.58;
  ctx.beginPath();
  ctx.moveTo(-cw, -1);
  ctx.bezierCurveTo(-cw, -o.h * 0.95, -cw * 0.4, -o.h * 1.05, 0, o.dent ? -o.h * 0.8 : -o.h);
  ctx.bezierCurveTo(cw * 0.4, -o.h * 1.05, cw, -o.h * 0.95, cw, -1);
  ctx.closePath();
  ctx.fillStyle = shade(ctx, 0, -o.h, 0, lighten(o.crown), o.crown);
  ctx.fill();
  outline(ctx);
  // band
  ctx.beginPath();
  ctx.moveTo(-cw * 0.98, -2);
  ctx.lineTo(cw * 0.98, -2);
  ctx.lineTo(cw * 0.96, -6);
  ctx.lineTo(-cw * 0.96, -6);
  ctx.closePath();
  ctx.fillStyle = o.band;
  ctx.fill();
  ctx.restore();
}

function lighten(c: string) {
  return c.startsWith("#") ? mix(c, "#ffffff", 0.35) : c;
}

function mix(a: string, b: string, t: number): string {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `rgb(${x.map((c, i) => Math.round(c + (y[i] - c) * t)).join(",")})`;
}

function cord(ctx: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number, sag: number, color = "#3b3f46", w = 0.9) {
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.quadraticCurveTo((x0 + x1) / 2, Math.max(y0, y1) + sag, x1, y1);
  ctx.strokeStyle = color;
  ctx.lineWidth = w;
  ctx.stroke();
}

function bowTie(k: CostumeKit, y: number, color = "#16181f", w = 9) {
  const { ctx } = k;
  const p = k.face(0, y) ?? [k.fx, k.fy + y * k.fs];
  const [x, yy] = p;
  ctx.save();
  ctx.translate(x, yy);
  ctx.fillStyle = shade(ctx, 0, -4, 4, mix(color.startsWith("#") ? color : "#16181f", "#ffffff", 0.25), color);
  for (const s of [-1, 1]) {
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.quadraticCurveTo(s * w * 0.6, -w * 0.55, s * w, -w * 0.45);
    ctx.quadraticCurveTo(s * w * 1.08, 0, s * w, w * 0.45);
    ctx.quadraticCurveTo(s * w * 0.6, w * 0.55, 0, 0);
    ctx.fill();
  }
  ctx.beginPath();
  ctx.ellipse(0, 0, w * 0.22, w * 0.3, 0, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.restore();
}

/** The lowest height where the body is still at least `min` units wide on each side. */
function belly(k: CostumeKit, min = 14): number {
  let y = 44;
  while (y > 0 && k.half(y) < min) y -= 1;
  return y;
}

/** Coat lapels: two panels from the shoulders down to a V over the lower body. */
function lapels(k: CostumeKit, color: string, edge: string, y0: number, depth: number, open = 0.32) {
  const { ctx } = k;
  const h0 = k.half(y0) * 0.98;
  const yb = Math.min(45, y0 + depth);
  const hb = k.half(yb) * 0.96;
  for (const s of [-1, 1]) {
    ctx.beginPath();
    ctx.moveTo(s * h0, y0);
    ctx.quadraticCurveTo(s * (h0 + 2), (y0 + yb) / 2, s * hb, yb);
    ctx.lineTo(s * hb * open * 0.2, yb);
    ctx.lineTo(s * h0 * open, y0 + 2);
    ctx.closePath();
    ctx.fillStyle = shade(ctx, 0, y0, yb, color, darken(color.startsWith("#") ? color : "#888888", 0.22));
    ctx.fill();
    outline(ctx, 0.6, 0.3);
    // the lapel's fold
    ctx.beginPath();
    ctx.moveTo(s * h0 * open, y0 + 2);
    ctx.lineTo(s * (h0 * open + 7), y0 + depth * 0.35);
    ctx.lineTo(s * hb * open * 0.2 + s * 2, yb - 2);
    ctx.strokeStyle = edge;
    ctx.lineWidth = 0.9;
    ctx.stroke();
  }
}

function lantern(k: CostumeKit, x: number, y: number) {
  const { ctx } = k;
  const flicker = 0.85 + 0.15 * Math.sin(k.time * 9) * Math.sin(k.time * 3.1);
  // glow
  const g = ctx.createRadialGradient(x, y + 6, 1, x, y + 6, 22);
  g.addColorStop(0, `rgba(255,214,140,${0.55 * flicker})`);
  g.addColorStop(1, "rgba(255,214,140,0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y + 6, 22, 0, Math.PI * 2);
  ctx.fill();
  // handle and body
  ctx.strokeStyle = "#2f3338";
  ctx.lineWidth = 1.1;
  ctx.beginPath();
  ctx.arc(x, y - 1, 3.6, Math.PI, 0);
  ctx.stroke();
  ctx.fillStyle = "#34383f";
  ctx.fillRect(x - 5, y, 10, 2.4);
  ctx.fillRect(x - 5, y + 12.4, 10, 2.4);
  ctx.fillStyle = `rgba(255,${Math.round(200 + 30 * flicker)},120,1)`;
  ctx.fillRect(x - 4, y + 2.4, 8, 10);
  ctx.strokeStyle = "#34383f";
  ctx.lineWidth = 0.8;
  for (const dx of [-4, 0, 4]) {
    ctx.beginPath();
    ctx.moveTo(x + dx, y + 2.4);
    ctx.lineTo(x + dx, y + 12.4);
    ctx.stroke();
  }
}

function magnifier(k: CostumeKit, x: number, y: number, r = 7, angle = 0.7) {
  const { ctx } = k;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.fillStyle = "#4a2f1f";
  ctx.beginPath();
  ctx.roundRect(-1.6, r, 3.2, r * 1.4, 1.2);
  ctx.fill();
  const lens = ctx.createRadialGradient(-r * 0.3, -r * 0.3, 1, 0, 0, r);
  lens.addColorStop(0, "rgba(255,255,255,0.85)");
  lens.addColorStop(0.5, "rgba(190,225,255,0.35)");
  lens.addColorStop(1, "rgba(160,200,240,0.5)");
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.fillStyle = lens;
  ctx.fill();
  ctx.lineWidth = 1.8;
  ctx.strokeStyle = "#c9a25a";
  ctx.stroke();
  ctx.restore();
}

function binoculars(k: CostumeKit, x: number, y: number, tilt = 0) {
  const { ctx } = k;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(tilt);
  ctx.fillStyle = "#252d38";
  ctx.fillRect(-5, -2, 10, 5);
  for (const side of [-1, 1]) {
    ctx.beginPath();
    ctx.ellipse(side * 7, 0, 6, 6.5, 0, 0, Math.PI * 2);
    ctx.fillStyle = "#293442";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(side * 7, 0, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#7cc4ff";
    ctx.fill();
    ctx.fillStyle = "#e0f3ff";
    ctx.fillRect(side * 7 - 2, -3, 2, 2);
  }
  ctx.restore();
}

function scales(k: CostumeKit, x: number, y: number, s = 1) {
  const { ctx } = k;
  const tilt = Math.sin(k.workTime * 5) * 0.27;
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(s, s);
  ctx.strokeStyle = "#c9a25a";
  ctx.fillStyle = "#d8b363";
  ctx.lineWidth = 1.3;
  ctx.beginPath();
  ctx.moveTo(0, -9);
  ctx.lineTo(0, 7);
  ctx.stroke();
  ctx.fillRect(-4, 6, 8, 1.8);
  ctx.save();
  ctx.translate(0, -8);
  ctx.rotate(tilt);
  ctx.beginPath();
  ctx.moveTo(-10, 0);
  ctx.lineTo(10, 0);
  ctx.stroke();
  for (const sx of [-1, 1]) {
    ctx.save();
    ctx.translate(sx * 10, 0);
    ctx.rotate(-tilt);
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(-3, 6);
    ctx.moveTo(0, 0);
    ctx.lineTo(3, 6);
    ctx.stroke();
    ctx.beginPath();
    ctx.ellipse(0, 6.5, 4.2, 1.5, 0, 0, Math.PI);
    ctx.fill();
    ctx.restore();
  }
  ctx.restore();
  ctx.restore();
}

function wrench(k: CostumeKit, x: number, y: number, angle = -0.6) {
  const { ctx } = k;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle + (k.busy ? Math.sin(k.time * 8) * 0.25 : 0));
  const g = shade(ctx, 0, -14, 14, "#eef2f6", "#9aa4b2");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.roundRect(-1.8, -4, 3.6, 18, 1.5);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(0, -7, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalCompositeOperation = "destination-out";
  ctx.beginPath();
  ctx.moveTo(-2.2, -14);
  ctx.lineTo(2.2, -14);
  ctx.lineTo(2.2, -7);
  ctx.lineTo(-2.2, -7);
  ctx.fill();
  ctx.globalCompositeOperation = "source-over";
  outline(ctx, 0.5, 0.3);
  ctx.restore();
}

// ---------------------------------------------------------------- the looks, per role

const watcher: [Look, Look] = [
  {
    id: 1,
    name: "Lighthouse keeper",
    reads: "yellow rain hat, a glowing lantern",
    draw: (k) => {
      const { ctx } = k;
      // sou'wester: a soft crown and a brim that dips at the back
      const x = headX(k);
      const y = k.top + 6;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(-0.12);
      ctx.beginPath();
      ctx.moveTo(-30, 3);
      ctx.quadraticCurveTo(-20, -4, 0, -4);
      ctx.quadraticCurveTo(20, -4, 30, 6);
      ctx.quadraticCurveTo(33, 11, 26, 9);
      ctx.quadraticCurveTo(0, 2, -26, 7);
      ctx.quadraticCurveTo(-33, 8, -30, 3);
      ctx.fillStyle = shade(ctx, 0, -5, 10, "#ffd84d", "#e0a81a");
      ctx.fill();
      outline(ctx);
      ctx.beginPath();
      ctx.moveTo(-17, -2);
      ctx.bezierCurveTo(-17, -20, 17, -20, 17, -2);
      ctx.closePath();
      ctx.fillStyle = shade(ctx, 0, -18, 0, "#ffe57a", "#f2b91f");
      ctx.fill();
      outline(ctx);
      ctx.restore();
      if (k.busy) {
        const sweep = Math.sin(k.workTime * 2.6);
        const [fx, fy] = k.face(0, 4) ?? [k.fx, k.fy + 4];
        const x = fx + 7 * sweep;
        mitten(k, x - 13, fy + 5, 4);
        mitten(k, x + 13, fy + 5, 4);
        binoculars(k, x, fy, sweep * 0.12);
      } else {
        const hx = k.half(18) + 4;
        lantern(k, hx + 2, 16);
        mitten(k, hx + 2, 12, 5);
      }
    },
  },
  {
    id: 2,
    name: "Night watchman",
    reads: "peaked cap with badge, binoculars",
    draw: (k) => {
      const { ctx } = k;
      const x = headX(k);
      const y = k.top + 7;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(-0.06);
      // peak
      ctx.beginPath();
      ctx.ellipse(0, 2, 20, 4.5, 0, 0, Math.PI);
      ctx.fillStyle = "#151b2b";
      ctx.fill();
      // crown
      ctx.beginPath();
      ctx.moveTo(-19, 1);
      ctx.lineTo(-23, -10);
      ctx.quadraticCurveTo(0, -18, 23, -10);
      ctx.lineTo(19, 1);
      ctx.closePath();
      ctx.fillStyle = shade(ctx, 0, -16, 1, "#3d4d78", "#24304f");
      ctx.fill();
      outline(ctx);
      ctx.fillStyle = "#151b2b";
      ctx.fillRect(-19, -3, 38, 4);
      // badge
      ctx.beginPath();
      ctx.moveTo(0, -12);
      ctx.lineTo(4, -8);
      ctx.lineTo(0, -4);
      ctx.lineTo(-4, -8);
      ctx.closePath();
      ctx.fillStyle = "#e4e9f2";
      ctx.fill();
      ctx.restore();
      // binoculars on a strap
      const yb = 22;
      const p = k.face(0, 28) ?? [k.fx, k.fy + 28];
      cord(ctx, -k.half(10) + 4, 6, p[0] - 6, p[1] - 2, 6);
      cord(ctx, k.half(10) - 4, 6, p[0] + 6, p[1] - 2, 6);
      ctx.save();
      ctx.translate(p[0], p[1]);
      for (const s of [-1, 1]) {
        ctx.beginPath();
        ctx.roundRect(s * 6 - 4.5, -5, 9, 12, 3);
        ctx.fillStyle = shade(ctx, 0, -5, 7, "#4a505c", "#22262e");
        ctx.fill();
        ctx.beginPath();
        ctx.ellipse(s * 6, 7, 4, 1.6, 0, 0, Math.PI * 2);
        ctx.fillStyle = "#7cc4ff";
        ctx.fill();
      }
      ctx.fillStyle = "#22262e";
      ctx.fillRect(-2, -2, 4, 3);
      ctx.restore();
      void yb;
    },
  },
];

const detective: [Look, Look] = [
  {
    id: 1,
    name: "Trench coat",
    reads: "tan trench coat, fedora, magnifier",
    draw: (k) => {
      lapels(k, "#c8a46a", "#8a6a3a", 14, 30);
      // belt
      const { ctx } = k;
      const yb = belly(k, 16) - 4;
      const hb = k.half(yb);
      ctx.fillStyle = "#a9864f";
      ctx.fillRect(-hb * 0.95, yb, hb * 1.9, 4);
      ctx.fillStyle = "#3b2b1a";
      ctx.fillRect(-3, yb - 0.5, 6, 5);
      brimHat(k, { crown: "#6b4f3a", band: "#2a1d14", brim: "#5b412e", w: 27, h: 16, dent: true, up: 7 });
      const sweep = Math.sin(k.workTime * 3.6);
      const hx = k.busy ? k.fx + 17 + 8 * sweep : k.half(12) + 7;
      const hy = k.busy ? k.fy + 4 + 3 * Math.cos(k.workTime * 3.6) : 2;
      magnifier(k, hx, hy, k.busy ? 9 : 7.5, k.busy ? -0.4 + 0.35 * sweep : 0.5);
      mitten(k, hx + (k.busy ? 5 : 4), hy + 11, 5);
    },
  },
  {
    id: 2,
    name: "Inspector",
    reads: "check cap with ear flaps, notebook, magnifier",
    draw: (k) => {
      const { ctx } = k;
      const x = headX(k);
      const y = k.top + 8;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(-0.05);
      ctx.beginPath();
      ctx.moveTo(-22, 2);
      ctx.bezierCurveTo(-22, -20, 22, -20, 22, 2);
      ctx.closePath();
      ctx.fillStyle = "#9a7b52";
      ctx.fill();
      // the check pattern
      ctx.save();
      ctx.clip();
      ctx.strokeStyle = "rgba(60,40,20,0.45)";
      ctx.lineWidth = 1.1;
      for (let i = -24; i <= 24; i += 5) {
        ctx.beginPath();
        ctx.moveTo(i, -22);
        ctx.lineTo(i, 4);
        ctx.moveTo(-24, i / 2 - 6);
        ctx.lineTo(24, i / 2 - 6);
        ctx.stroke();
      }
      ctx.restore();
      outline(ctx);
      // front and back peaks, ear flaps
      ctx.fillStyle = "#86683f";
      ctx.beginPath();
      ctx.ellipse(-4, 2.5, 13, 3.4, 0.05, 0, Math.PI);
      ctx.fill();
      for (const s of [-1, 1]) {
        ctx.beginPath();
        ctx.moveTo(s * 20, -2);
        ctx.quadraticCurveTo(s * 25, 6, s * 19, 10);
        ctx.quadraticCurveTo(s * 16, 4, s * 17, -2);
        ctx.fill();
      }
      ctx.fillStyle = "#5a4127";
      ctx.beginPath();
      ctx.arc(0, -15, 2.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      // notebook in one mitten, magnifier in the other
      const hl = -k.half(16) - 6;
      ctx.save();
      ctx.translate(hl, 14);
      ctx.rotate(-0.25);
      ctx.fillStyle = "#2e3c5c";
      ctx.fillRect(-6, -8, 12, 15);
      ctx.fillStyle = "#f6f1e7";
      ctx.fillRect(-4.5, -6.5, 9, 12);
      ctx.strokeStyle = "rgba(40,50,80,0.5)";
      ctx.lineWidth = 0.6;
      for (let i = 0; i < 4; i++) {
        ctx.beginPath();
        ctx.moveTo(-3.5, -4 + i * 2.6);
        ctx.lineTo(3.5, -4 + i * 2.6);
        ctx.stroke();
      }
      ctx.restore();
      mitten(k, hl + 4, 20, 5);
      const hr = k.half(12) + 5;
      magnifier(k, hr + 2, 2, 7, 0.5);
      mitten(k, hr + 6, 13, 5);
    },
  },
];

function tray(k: CostumeKit, x: number, y: number) {
  const { ctx } = k;
  ctx.save();
  ctx.translate(x, y);
  ctx.beginPath();
  ctx.ellipse(0, 0, 15, 4.2, 0, 0, Math.PI * 2);
  ctx.fillStyle = shade(ctx, 0, -4, 4, "#f4f6fa", "#a7b0bf");
  ctx.fill();
  ctx.lineWidth = 0.8;
  ctx.strokeStyle = "#8a93a3";
  ctx.stroke();
  // the folded memo with a glowing seal
  ctx.save();
  ctx.rotate(-0.12);
  ctx.fillStyle = "#fbf8f1";
  ctx.beginPath();
  ctx.moveTo(-8, -1.5);
  ctx.lineTo(8, -1.5);
  ctx.lineTo(8, -9);
  ctx.lineTo(-8, -9);
  ctx.closePath();
  ctx.fill();
  outline(ctx, 0.5, 0.3);
  ctx.beginPath();
  ctx.moveTo(-8, -9);
  ctx.lineTo(0, -4.5);
  ctx.lineTo(8, -9);
  ctx.strokeStyle = "rgba(80,70,50,0.45)";
  ctx.stroke();
  // the glowing seal: a soft halo under the dot (no shadowBlur, it is the costly part of a frame)
  ctx.fillStyle = k.glow;
  ctx.globalAlpha = 0.3;
  ctx.beginPath();
  ctx.arc(0, -4.6, 3.6, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.beginPath();
  ctx.arc(0, -4.6, 1.8, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  ctx.restore();
}

function writing(k: CostumeKit, x: number, y: number) {
  const { ctx } = k;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-0.14);
  ctx.fillStyle = "#fbf8f1";
  ctx.fillRect(-12, -8, 23, 17);
  ctx.fillStyle = "#8a93a3";
  ctx.fillRect(-8, -4, 12, 1.2);
  ctx.fillRect(-8, 0, 9, 1.2);
  const stroke = Math.sin(k.workTime * 9);
  ctx.fillRect(-8, 4, 7 + 3 * stroke, 1.2);
  const pen = 3 * stroke;
  mitten(k, pen + 9, -3, 4);
  ctx.strokeStyle = "#24304f";
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(pen + 1, 5);
  ctx.lineTo(pen + 10, -8);
  ctx.stroke();
  ctx.restore();
}

const narrator: [Look, Look] = [
  {
    id: 1,
    name: "Butler",
    reads: "bow tie and collar, silver tray with the memo",
    draw: (k) => {
      const { ctx } = k;
      // white collar points under the bow tie
      const p = k.face(0, 20) ?? [k.fx, k.fy + 20];
      ctx.fillStyle = "#ffffff";
      for (const s of [-1, 1]) {
        ctx.beginPath();
        ctx.moveTo(p[0], p[1] - 1);
        ctx.lineTo(p[0] + s * 8, p[1] - 3);
        ctx.lineTo(p[0] + s * 4, p[1] + 5);
        ctx.closePath();
        ctx.fill();
      }
      bowTie(k, 20, "#14161c", 8.5);
      const hx = k.half(4) + 6;
      if (k.busy) {
        mitten(k, k.fx - 10, k.fy + 26, 4);
        writing(k, k.fx + 3, k.fy + 23);
      } else {
        tray(k, hx + 4, -4);
        mitten(k, hx + 4, 1, 5);
      }
    },
  },
  {
    id: 2,
    name: "Head butler",
    reads: "black tailcoat, bow tie, monocle, sealed scroll",
    draw: (k) => {
      lapels(k, "#2a2d36", "#4a4f5c", 16, 28, 0.38);
      const { ctx } = k;
      const p = k.face(0, 21) ?? [k.fx, k.fy + 21];
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.moveTo(p[0] - 6, p[1] - 3);
      ctx.lineTo(p[0] + 6, p[1] - 3);
      ctx.lineTo(p[0], p[1] + 14);
      ctx.closePath();
      ctx.fill();
      bowTie(k, 20, "#14161c", 7.5);
      // monocle on the right eye
      const m = k.face(12.5, 1);
      if (m) {
        ctx.beginPath();
        ctx.arc(m[0], m[1], 6.5 * k.fs, 0, Math.PI * 2);
        ctx.lineWidth = 1.2;
        ctx.strokeStyle = "#c9a25a";
        ctx.stroke();
        cord(ctx, m[0] + 5, m[1] + 4, m[0] + 9, m[1] + 22, 4, "#c9a25a", 0.6);
      }
      // a rolled memo with a wax seal
      const hx = k.half(10) + 6;
      ctx.save();
      ctx.translate(hx + 2, 6);
      ctx.rotate(-0.5);
      ctx.fillStyle = shade(ctx, 0, -3, 3, "#fbf8f1", "#e2d8c3");
      ctx.beginPath();
      ctx.roundRect(-11, -3, 22, 6, 3);
      ctx.fill();
      outline(ctx, 0.5, 0.3);
      ctx.beginPath();
      ctx.arc(2, 3, 2.6, 0, Math.PI * 2);
      ctx.fillStyle = "#b3392e";
      ctx.fill();
      ctx.restore();
      mitten(k, hx + 4, 10, 5);
    },
  },
];

const cartographer: [Look, Look] = [
  {
    id: 1,
    name: "Land surveyor",
    reads: "explorer hat, map roll, compass",
    draw: (k) => {
      brimHat(k, { crown: "#c9b48a", band: "#6b5434", brim: "#b8a273", w: 30, h: 13, up: 6 });
      const { ctx } = k;
      // the compass on a cord
      const p = k.face(0, 26) ?? [k.fx, k.fy + 26];
      cord(ctx, -10, k.fy + 14, p[0], p[1] - 5, 3, "#6b5434", 0.8);
      cord(ctx, 10, k.fy + 14, p[0], p[1] - 5, 3, "#6b5434", 0.8);
      ctx.beginPath();
      ctx.arc(p[0], p[1], 5.5, 0, Math.PI * 2);
      ctx.fillStyle = shade(ctx, 0, p[1] - 5, p[1] + 5, "#f2d28a", "#b98d3a");
      ctx.fill();
      ctx.beginPath();
      ctx.arc(p[0], p[1], 4, 0, Math.PI * 2);
      ctx.fillStyle = "#fbf8f1";
      ctx.fill();
      const a = Math.sin(k.time * 0.8) * 0.4;
      ctx.beginPath();
      ctx.moveTo(p[0] + Math.sin(a) * 3.5, p[1] - Math.cos(a) * 3.5);
      ctx.lineTo(p[0] - Math.sin(a) * 3.5, p[1] + Math.cos(a) * 3.5);
      ctx.strokeStyle = "#c8392e";
      ctx.lineWidth = 1.1;
      ctx.stroke();
      // the map roll under the arm
      const hx = -k.half(18) - 4;
      ctx.save();
      ctx.translate(hx, 18);
      ctx.rotate(0.5);
      ctx.fillStyle = shade(ctx, 0, -3.5, 3.5, "#f3e7c6", "#d2bf8f");
      ctx.beginPath();
      ctx.roundRect(-14, -3.5, 28, 7, 3.5);
      ctx.fill();
      outline(ctx, 0.5, 0.3);
      ctx.strokeStyle = k.glow;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(-6, -3.5);
      ctx.lineTo(-6, 3.5);
      ctx.moveTo(6, -3.5);
      ctx.lineTo(6, 3.5);
      ctx.stroke();
      ctx.restore();
      mitten(k, hx + 3, 22, 5);
    },
  },
  {
    id: 2,
    name: "Field engineer",
    reads: "flat cap, survey tripod with a sight",
    draw: (k) => {
      const { ctx } = k;
      const x = headX(k);
      const y = k.top + 7;
      ctx.save();
      ctx.translate(x, y);
      ctx.beginPath();
      ctx.moveTo(-21, 2);
      ctx.bezierCurveTo(-21, -15, 18, -17, 21, -3);
      ctx.quadraticCurveTo(30, 2, 18, 4);
      ctx.closePath();
      ctx.fillStyle = shade(ctx, 0, -14, 4, "#7f9a7a", "#55705a");
      ctx.fill();
      outline(ctx);
      ctx.restore();
      // the tripod with its sight, beside the bot
      const hx = k.half(20) + 10;
      ctx.strokeStyle = "#5b4636";
      ctx.lineWidth = 1.6;
      for (const dx of [-6, 0, 6]) {
        ctx.beginPath();
        ctx.moveTo(hx, 6);
        ctx.lineTo(hx + dx, 44);
        ctx.stroke();
      }
      ctx.fillStyle = shade(ctx, 0, -2, 6, "#f2c94c", "#c99a1e");
      ctx.beginPath();
      ctx.roundRect(hx - 8, -2, 16, 8, 2);
      ctx.fill();
      outline(ctx, 0.5, 0.3);
      ctx.beginPath();
      ctx.arc(hx - 8, 2, 2.6, 0, Math.PI * 2);
      ctx.fillStyle = k.glow;
      ctx.fill();
      mitten(k, hx - 9, 9, 4.6);
    },
  },
];

const skeptic: [Look, Look] = [
  {
    id: 1,
    name: "Judge",
    reads: "white curled wig, bands, golden scales",
    draw: (k) => {
      const { ctx } = k;
      // the wig: rows of white curls over the top and down the sides
      const x = headX(k);
      const t = k.top + 4;
      ctx.save();
      ctx.translate(x, t);
      const curl = (cx: number, cy: number, r: number) => {
        const g = ctx.createRadialGradient(cx - r * 0.3, cy - r * 0.3, 0.5, cx, cy, r);
        g.addColorStop(0, "#ffffff");
        g.addColorStop(1, "#d7d9df");
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();
      };
      const w = Math.min(30, k.half(k.top + 8) + 2);
      for (let i = -4; i <= 4; i++) curl((i * w) / 4.4, -3 + Math.abs(i) * 0.9, 5.2);
      for (let i = -3; i <= 3; i++) curl((i * w) / 4.4, -8.5 + Math.abs(i) * 0.9, 4.8);
      ctx.restore();
      // side rolls hug the body down to the cheeks
      for (const s of [-1, 1]) for (let j = 0; j < 3; j++) {
        const yy = t + 4 + j * 7;
        curl(s * (k.half(yy) - 2) + (headX(k) - k.fx) * 0.5, yy, 4.6);
      }
      // the black robe and a white jabot, low on the body
      const yb = belly(k);
      lapels(k, "#1d1f27", "#3b3f4c", yb - 16, 20, 0.5);
      const jx = k.fx + Math.sin(k.yaw) * 6;
      ctx.fillStyle = "#ffffff";
      for (let i = 0; i < 3; i++) {
        ctx.beginPath();
        ctx.ellipse(jx, yb - 13 + i * 4.2, 5.5 - i * 0.8, 2.6, 0, 0, Math.PI * 2);
        ctx.fill();
      }
      // held close to the body so the pans stay inside the avatar's box (it sits next to text in panels)
      const hx = k.half(4) + 2;
      scales(k, hx + 2, -2, 1.15);
      mitten(k, hx + 2, 11, 4.8);
    },
  },
  {
    id: 2,
    name: "Referee",
    reads: "striped referee collar, whistle, a red card",
    draw: (k) => {
      const { ctx } = k;
      // a striped referee shirt over the lower body, with a black collar
      const yb = belly(k);
      const y0 = yb - 16;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(-k.half(y0), y0);
      for (let y = y0; y <= yb + 4; y += 2) ctx.lineTo(-k.half(y) * 0.97, y);
      for (let y = yb + 4; y >= y0; y -= 2) ctx.lineTo(k.half(y) * 0.97, y);
      ctx.closePath();
      ctx.clip();
      for (let x = -50; x < 50; x += 7) {
        ctx.fillStyle = (x / 7) % 2 === 0 ? "#f4f6fa" : "#1c1f26";
        ctx.fillRect(x, y0, 3.5, 30);
        ctx.fillStyle = "#f4f6fa";
        ctx.fillRect(x + 3.5, y0, 3.5, 30);
      }
      ctx.fillStyle = "#1c1f26";
      ctx.fillRect(-50, y0, 100, 2.6);
      ctx.restore();
      // whistle on a cord
      const w: [number, number] = [k.fx - 9, y0 + 7];
      cord(ctx, -5, y0 + 1, w[0], w[1] - 2, 2, "#d94a3a", 0.7);
      ctx.fillStyle = shade(ctx, 0, w[1] - 3, w[1] + 3, "#f4f6fa", "#9aa4b2");
      ctx.beginPath();
      ctx.roundRect(w[0] - 5, w[1] - 2.5, 9, 5, 2.5);
      ctx.fill();
      // the raised card
      const hx = k.half(0) + 6;
      ctx.save();
      ctx.translate(hx + 2, -10);
      ctx.rotate(0.18 + (k.busy ? Math.sin(k.time * 6) * 0.1 : 0));
      ctx.fillStyle = "#e5453b";
      ctx.beginPath();
      ctx.roundRect(-5, -8, 10, 14, 1.5);
      ctx.fill();
      ctx.restore();
      mitten(k, hx + 2, -2, 4.6);
      scales(k, -k.half(12) - 6, 6, 0.65);
    },
  },
];

const operator: [Look, Look] = [
  {
    id: 1,
    name: "Mechanic",
    reads: "yellow hard hat, wrench, tool belt",
    draw: (k) => {
      const { ctx } = k;
      const x = headX(k);
      const y = k.top + 6;
      ctx.save();
      ctx.translate(x, y);
      ctx.beginPath();
      ctx.ellipse(0, 1, 24, 4, 0, 0, Math.PI * 2);
      ctx.fillStyle = "#e0a81a";
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(-18, 0);
      ctx.bezierCurveTo(-18, -20, 18, -20, 18, 0);
      ctx.closePath();
      ctx.fillStyle = shade(ctx, 0, -16, 0, "#ffe066", "#f2b91f");
      ctx.fill();
      outline(ctx);
      ctx.fillStyle = "rgba(255,255,255,0.55)";
      ctx.fillRect(-1.5, -15, 3, 14);
      ctx.restore();
      // tool belt, low on the body
      const yb = belly(k, 18) - 4;
      const hb = k.half(yb);
      ctx.fillStyle = "#6b4a2b";
      ctx.fillRect(-hb * 0.95, yb, hb * 1.9, 4.5);
      ctx.fillStyle = "#8a6239";
      ctx.fillRect(-hb * 0.55, yb + 3, 8, 7);
      ctx.fillRect(hb * 0.3, yb + 3, 8, 7);
      const hx = k.half(10) + 6;
      wrench(k, hx + 4, -2, -0.4);
      mitten(k, hx + 3, 9, 5);
    },
  },
  {
    id: 2,
    name: "Engineer",
    reads: "headset with mic, control tablet with glowing switches",
    draw: (k) => {
      const { ctx } = k;
      // headset band over the head, cups at the temples, mic boom
      const x = headX(k);
      ctx.beginPath();
      ctx.arc(x, k.top + 18, 22, Math.PI * 1.08, Math.PI * 1.92);
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#2d3340";
      ctx.stroke();
      const cupL = k.face(-27, 1);
      const cupR = k.face(27, 1);
      for (const c of [cupL, cupR]) {
        if (!c) continue;
        ctx.beginPath();
        ctx.ellipse(c[0], c[1], 4.5, 6.5, 0, 0, Math.PI * 2);
        ctx.fillStyle = shade(ctx, 0, c[1] - 6, c[1] + 6, "#4a5263", "#232833");
        ctx.fill();
      }
      if (cupL) {
        const m = k.face(-10, 18) ?? [cupL[0] + 14, cupL[1] + 14];
        ctx.beginPath();
        ctx.moveTo(cupL[0], cupL[1] + 4);
        ctx.quadraticCurveTo(cupL[0] + 2, m[1], m[0], m[1]);
        ctx.lineWidth = 1.2;
        ctx.strokeStyle = "#2d3340";
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(m[0], m[1], 2, 0, Math.PI * 2);
        ctx.fillStyle = k.glow;
        ctx.fill();
      }
      // the control tablet
      const hx = k.half(14) + 6;
      ctx.save();
      ctx.translate(hx + 5, 10);
      ctx.rotate(-0.2);
      ctx.fillStyle = "#3a4150";
      ctx.beginPath();
      ctx.roundRect(-9, -12, 18, 22, 2.5);
      ctx.fill();
      ctx.fillStyle = "#151a24";
      ctx.fillRect(-7, -10, 14, 18);
      const blink = Math.floor(k.time * 3) % 3;
      ["#3fdf8f", "#e8b04a", "#ff5c5c"].forEach((c, i) => {
        ctx.fillStyle = i === blink && k.busy ? "#ffffff" : c;
        ctx.beginPath();
        ctx.arc(-4 + i * 4, -6, 1.4, 0, Math.PI * 2);
        ctx.fill();
      });
      for (let i = 0; i < 3; i++) {
        ctx.fillStyle = "#c9d2de";
        ctx.fillRect(-5 + i * 4, -1, 2, 6);
        ctx.fillStyle = k.glow;
        ctx.fillRect(-5 + i * 4, i % 2 ? 2 : -1, 2, 2);
      }
      ctx.restore();
      mitten(k, hx + 1, 18, 5);
    },
  },
];

const market: [Look, Look] = [
  {
    id: 1,
    name: "Trader",
    reads: "green eyeshade visor, curling ticker tape",
    draw: (k) => {
      const { ctx } = k;
      const x = headX(k);
      const y = k.top + 9;
      ctx.save();
      ctx.translate(x, y);
      // the band and the translucent green shade
      ctx.fillStyle = "#1c5f3d";
      ctx.fillRect(-21, -3, 42, 4);
      ctx.beginPath();
      ctx.moveTo(-18, 1);
      ctx.quadraticCurveTo(0, 12, 18, 1);
      ctx.lineTo(16, -1);
      ctx.quadraticCurveTo(0, 6, -16, -1);
      ctx.closePath();
      ctx.fillStyle = "rgba(46,190,110,0.75)";
      ctx.fill();
      outline(ctx, 0.5, 0.3);
      ctx.restore();
      // ticker tape curling out of a mitten
      const hx = k.half(10) + 4;
      ctx.beginPath();
      ctx.moveTo(hx, 6);
      for (let i = 1; i <= 16; i++) {
        const t = i / 16;
        ctx.lineTo(hx + 4 + t * 16 + Math.sin(t * 7 + k.time * 2) * 3, 6 + t * 30 + Math.cos(t * 5) * 4);
      }
      ctx.lineWidth = 4;
      ctx.strokeStyle = "#fbf8f1";
      ctx.stroke();
      ctx.lineWidth = 0.7;
      ctx.setLineDash([1.5, 1.8]);
      ctx.strokeStyle = "#2fcb7a";
      ctx.stroke();
      ctx.setLineDash([]);
      mitten(k, hx + 2, 6, 5);
    },
  },
  {
    id: 2,
    name: "Floor trader",
    reads: "bright trading jacket, phone handset, mini ticker board",
    draw: (k) => {
      lapels(k, "#2f7fe0", "#ffd84d", 16, 28, 0.36);
      const { ctx } = k;
      // a jacket badge
      const b = k.face(-14, 30) ?? [k.fx - 14, k.fy + 30];
      ctx.fillStyle = "#ffd84d";
      ctx.fillRect(b[0] - 4, b[1] - 3, 8, 6);
      // phone handset at the side of the head
      const hx = k.half(-6) + 3;
      ctx.save();
      ctx.translate(hx + 2, -4);
      ctx.rotate(0.35);
      ctx.fillStyle = shade(ctx, 0, -10, 10, "#3a4150", "#1c2029");
      ctx.beginPath();
      ctx.roundRect(-2.6, -11, 5.2, 22, 2.6);
      ctx.fill();
      ctx.restore();
      mitten(k, hx + 5, 6, 4.6);
      // the mini ticker board, floating at the other side
      const lx = -k.half(4) - 16;
      ctx.fillStyle = "#0b1520";
      ctx.beginPath();
      ctx.roundRect(lx - 8, -16, 16, 10, 1.5);
      ctx.fill();
      for (let i = 0; i < 5; i++) {
        const up = Math.sin(k.time * 2 + i * 1.7) > 0;
        ctx.fillStyle = up ? "#3fdf8f" : "#ff5c5c";
        const h = 2 + Math.abs(Math.sin(k.time * 2 + i)) * 4;
        ctx.fillRect(lx - 6 + i * 2.8, -8 - h, 1.6, h);
      }
    },
  },
];

/** The two looks of each role. Look 1 is the default until the captain picks. */
export const LOOKS: Readonly<Record<RoleId, [Look, Look]>> = { watcher, detective, narrator, cartographer, skeptic, operator, market };

/** The look every avatar of `role` wears: look 1, the board's default. */
export const DEFAULT_LOOK: LookId = 1;

export function defaultLook(role: RoleId): Look {
  return LOOKS[role][DEFAULT_LOOK - 1];
}

// ---------------------------------------------------------------- the optional 8th: Calendar

export const calendarLooks: [Look, Look] = [
  {
    id: 1,
    name: "Concierge",
    reads: "pillbox hat, clipboard with today's plan",
    draw: (k) => {
      const { ctx } = k;
      const x = headX(k) + 4;
      const y = k.top + 3;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(0.12);
      ctx.beginPath();
      ctx.roundRect(-10, -9, 20, 10, 2);
      ctx.fillStyle = shade(ctx, 0, -9, 1, "#d9534f", "#a8322e");
      ctx.fill();
      ctx.fillStyle = "#e8b04a";
      ctx.fillRect(-10, -2.5, 20, 2);
      ctx.restore();
      bowTie(k, 21, "#a8322e", 6.5);
      const hx = k.half(14) + 6;
      ctx.save();
      ctx.translate(hx + 4, 10);
      ctx.rotate(-0.15);
      ctx.fillStyle = "#7a5634";
      ctx.beginPath();
      ctx.roundRect(-8, -11, 16, 21, 1.5);
      ctx.fill();
      ctx.fillStyle = "#fbf8f1";
      ctx.fillRect(-6.5, -8, 13, 16);
      ctx.fillStyle = "#b9c0cc";
      ctx.fillRect(-3, -12, 6, 3);
      for (let i = 0; i < 4; i++) {
        ctx.fillStyle = i === 1 ? k.glow : "rgba(40,50,80,0.45)";
        ctx.fillRect(-5, -5 + i * 3.2, i === 1 ? 10 : 8, 1.2);
      }
      ctx.restore();
      mitten(k, hx + 1, 18, 5);
    },
  },
  {
    id: 2,
    name: "Planner",
    reads: "round glasses, a calendar page with a ringed date",
    draw: (k) => {
      const { ctx } = k;
      for (const s of [-1, 1]) {
        const c = k.face(s * 12.5, 1);
        if (!c) continue;
        ctx.beginPath();
        ctx.arc(c[0], c[1], 7 * k.fs, 0, Math.PI * 2);
        ctx.lineWidth = 1.3;
        ctx.strokeStyle = "#3b2b1a";
        ctx.stroke();
      }
      const hx = k.half(6) + 7;
      ctx.save();
      ctx.translate(hx + 4, 2);
      ctx.rotate(0.1);
      ctx.fillStyle = "#fbf8f1";
      ctx.beginPath();
      ctx.roundRect(-9, -10, 18, 20, 2);
      ctx.fill();
      ctx.fillStyle = "#d9534f";
      ctx.fillRect(-9, -10, 18, 5);
      ctx.fillStyle = "rgba(40,50,80,0.35)";
      for (let r = 0; r < 3; r++) for (let c = 0; c < 4; c++) ctx.fillRect(-7 + c * 4, -2 + r * 4, 2.4, 2.4);
      ctx.beginPath();
      ctx.arc(-1.8 + 4, 2 + 0.2, 2.8, 0, Math.PI * 2);
      ctx.strokeStyle = k.glow;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();
      mitten(k, hx + 1, 12, 5);
    },
  },
];
