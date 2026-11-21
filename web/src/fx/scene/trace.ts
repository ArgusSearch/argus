// The investigation trace (A7): a thin HUD polyline that walks above the blocks from the alarmed metric through
// every metric and log the investigation checks, 600 ms per hop, with a stem down to each block it visits.
// The numbered "+" markers are DOM (labels.ts); this file draws the lines and says where the markers go.

import { BufferAttribute, BufferGeometry, DoubleSide, Mesh, ShaderMaterial } from "three";
import type { Env } from "./env";
import type { SceneModel } from "./model";
import { FOG, FOG_UNIFORMS } from "./shaders/common";

const HOP_SECONDS = 0.6;
/** height of the trace above the top of a block */
export const TRACE_LIFT = 0.8;
const CAPACITY = 96;

const vertex = /* glsl */ `
attribute vec3 aA;
attribute vec3 aB;
attribute vec2 aCorner;  // side, end
attribute vec2 aProg;    // progress (in hops) at A and at B
uniform vec2 uResolution;
uniform float uPixelRatio;
uniform float uWidth;
varying float vSide;
varying float vWidth;
varying float vFull;
varying float vProg;
varying vec3 vWorld;

void main() {
  vec4 ca = projectionMatrix * viewMatrix * vec4(aA, 1.0);
  vec4 cb = projectionMatrix * viewMatrix * vec4(aB, 1.0);
  vec2 half_ = uResolution * 0.5;
  vec2 dir = cb.xy / cb.w * half_ - ca.xy / ca.w * half_;
  float len = length(dir);
  dir = len > 1e-4 ? dir / len : vec2(1.0, 0.0);
  vec2 nrm = vec2(-dir.y, dir.x);
  float width = uWidth * uPixelRatio;
  float full = width + 2.0;
  vec4 c = aCorner.y < 0.5 ? ca : cb;
  c.xy += nrm * aCorner.x * (full * 0.5) / half_ * c.w;
  gl_Position = c;
  vSide = aCorner.x;
  vWidth = width;
  vFull = full;
  vProg = mix(aProg.x, aProg.y, aCorner.y);
  vWorld = aCorner.y < 0.5 ? aA : aB;
}
`;

const fragment = /* glsl */ `
uniform vec3 uHud;
uniform float uAlpha;
uniform float uDrawn;
${FOG_UNIFORMS}
varying float vSide;
varying float vWidth;
varying float vFull;
varying float vProg;
varying vec3 vWorld;

${FOG}

void main() {
  if (vProg > uDrawn) discard;
  float d = abs(vSide) * vFull * 0.5;
  float cover = clamp(vWidth * 0.5 + 0.5 - d, 0.0, 1.0);
  // the newest part of the walk is the brightest
  float head = exp(-max(uDrawn - vProg, 0.0) * 1.2);
  float a = uAlpha * cover * (0.75 + 0.25 * head) * (1.0 - fogAmount(length(vWorld - cameraPosition)));
  gl_FragColor = vec4(uHud * (1.0 + 0.6 * head), a);
}
`;

export interface TraceMarker {
  id: string;
  /** step numbers of the trail that touched this block, ascending */
  steps: number[];
  /** hop at which the walk reaches it */
  hop: number;
  /** where the "+" sits */
  point: [number, number, number];
}

export class Trace {
  readonly mesh: Mesh;
  readonly material: ShaderMaterial;
  markers: TraceMarker[] = [];
  /** hops drawn so far, animated toward `hops` */
  drawn = 0;
  hops = 0;
  private key = "";

  constructor(env: Env) {
    this.material = new ShaderMaterial({
      vertexShader: vertex,
      fragmentShader: fragment,
      uniforms: {
        uResolution: env.uResolution,
        uPixelRatio: env.uPixelRatio,
        uHud: env.uHud,
        uFogColor: env.uFogColor,
        uFogNear: env.uFogNear,
        uFogDensity: env.uFogDensity,
        uWidth: { value: 1.25 },
        uAlpha: { value: 0 },
        uDrawn: { value: 0 },
      },
      transparent: true,
      depthWrite: false,
      depthTest: false,
      side: DoubleSide,
    });
    this.mesh = new Mesh(new BufferGeometry(), this.material);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 7;
  }

  /**
   * Rebuilds the walk when the trace changed. `top(id)` is the point on top of a block. A new investigation
   * (a different first entry, or a shorter trace) starts drawing from zero.
   */
  set(trace: SceneModel["trace"], top: (id: string) => [number, number, number] | undefined): void {
    const key = trace.map((t) => `${t.id}@${t.step}`).join(" ");
    if (key === this.key) return;
    // a growing walk keeps what is drawn; anything else is a new investigation
    const restart = !this.key || !key.startsWith(this.key);
    this.key = key;

    // the walk starts at the anomaly and goes from place to place: its returns to the anomaly between checks
    // and consecutive repeats collapse, so it reads as one path and not as a star of spokes
    const walk: { id: string; point: [number, number, number] }[] = [];
    const steps = new Map<string, Set<number>>();
    const anchor = trace[0]?.id;
    for (const t of trace) {
      const p = top(t.id);
      if (!p) continue;
      if (t.id === anchor && walk.length > 0) continue;
      if (!steps.has(t.id)) steps.set(t.id, new Set());
      steps.get(t.id)?.add(t.step);
      if (walk.length === 0 || walk[walk.length - 1].id !== t.id) {
        walk.push({ id: t.id, point: [p[0], p[1] + TRACE_LIFT, p[2]] });
      }
    }
    const stops = walk.slice(0, CAPACITY);
    const firstHop = new Map<string, number>();
    stops.forEach((s, i) => firstHop.has(s.id) || firstHop.set(s.id, i));
    this.markers = [...firstHop.entries()].map(([id, hop]) => ({
      id,
      hop,
      steps: [...(steps.get(id) ?? [])].sort((a, b) => a - b),
      point: stops[hop].point,
    }));
    this.hops = Math.max(0, stops.length - 1);
    if (restart) this.drawn = 0;
    this.drawn = Math.min(this.drawn, this.hops);

    // segments: one per hop, plus a stem from each first visit down to its block
    const segs: { a: number[]; b: number[]; pa: number; pb: number }[] = [];
    for (let i = 1; i < stops.length; i++) segs.push({ a: stops[i - 1].point, b: stops[i].point, pa: i - 1, pb: i });
    for (const m of this.markers) {
      const [x, y, z] = m.point;
      segs.push({ a: [x, y, z], b: [x, y - TRACE_LIFT + 0.04, z], pa: m.hop, pb: m.hop });
    }
    const n = segs.length;
    const aA = new Float32Array(n * 4 * 3);
    const aB = new Float32Array(n * 4 * 3);
    const corner = new Float32Array(n * 4 * 2);
    const prog = new Float32Array(n * 4 * 2);
    const index = new Uint32Array(n * 6);
    segs.forEach((s, q) => {
      for (let v = 0; v < 4; v++) {
        aA.set(s.a, (q * 4 + v) * 3);
        aB.set(s.b, (q * 4 + v) * 3);
        corner[(q * 4 + v) * 2] = v % 2 === 0 ? -1 : 1;
        corner[(q * 4 + v) * 2 + 1] = v < 2 ? 0 : 1;
        prog[(q * 4 + v) * 2] = s.pa;
        prog[(q * 4 + v) * 2 + 1] = s.pb;
      }
      const base = q * 4;
      index.set([base, base + 1, base + 2, base + 2, base + 1, base + 3], q * 6);
    });
    const geometry = new BufferGeometry();
    geometry.setAttribute("aA", new BufferAttribute(aA, 3));
    geometry.setAttribute("aB", new BufferAttribute(aB, 3));
    geometry.setAttribute("aCorner", new BufferAttribute(corner, 2));
    geometry.setAttribute("aProg", new BufferAttribute(prog, 2));
    geometry.setAttribute("position", new BufferAttribute(new Float32Array(n * 4 * 3), 3));
    geometry.setIndex(new BufferAttribute(index, 1));
    this.mesh.geometry.dispose();
    this.mesh.geometry = geometry;
  }

  /** Advances the walk; returns the hop progress for the markers. `instant` jumps to the end. */
  update(dt: number, alpha: number, instant: boolean): number {
    if (instant) this.drawn = this.hops;
    else if (this.drawn < this.hops) {
      const behind = this.hops - this.drawn;
      this.drawn = Math.min(this.hops, this.drawn + dt * Math.max(1 / HOP_SECONDS, behind / 1.2));
    }
    this.material.uniforms.uDrawn.value = this.drawn + 1e-3;
    this.material.uniforms.uAlpha.value = alpha;
    this.mesh.visible = alpha > 0.001 && this.markers.length > 0;
    return this.drawn;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.material.dispose();
  }
}
