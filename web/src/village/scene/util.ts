// Small helpers the village scene shares: a soft radial glow texture, a seeded random source, easing.

import { CanvasTexture, Color, LinearFilter, SRGBColorSpace } from "three";

let glow: CanvasTexture | null = null;

/** A white radial falloff, used for halos and the light spill in front of the doors (tinted by the material). */
export function glowTexture(): CanvasTexture {
  if (glow) return glow;
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(255,255,255,0.55)");
  g.addColorStop(0.6, "rgba(255,255,255,0.12)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  glow = new CanvasTexture(canvas);
  glow.colorSpace = SRGBColorSpace;
  glow.minFilter = LinearFilter;
  glow.magFilter = LinearFilter;
  glow.generateMipmaps = false;
  return glow;
}

/** mulberry32: the same village every load. */
export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
export const smooth = (x: number) => {
  const t = clamp01(x);
  return t * t * (3 - 2 * t);
};
export const easeInOut = (x: number) => {
  const t = clamp01(x);
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
};
export const approach = (x: number, target: number, rate: number, dt: number) => x + (target - x) * (1 - Math.exp(-rate * dt));

/** A color scaled past 1 so the bloom picks it up (the scene renders into a half-float buffer). */
export function hot(hex: string, intensity: number): Color {
  return new Color(hex).multiplyScalar(intensity);
}
