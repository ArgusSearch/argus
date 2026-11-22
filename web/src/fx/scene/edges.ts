// Typed edges as curved ribbons with exact pixel widths, plus the points that flow along them (A9).
// One draw call for all ribbons, one for all flow points; the live state of every link is one texture row.

import {
  BufferAttribute,
  BufferGeometry,
  DataTexture,
  DoubleSide,
  FloatType,
  Mesh,
  NearestFilter,
  Points,
  RGBAFormat,
  ShaderMaterial,
  Vector3,
} from "three";
import type { Env } from "./env";
import { BLOCK } from "./layout";
import type { SceneLink } from "./model";
import { flowFragment, flowVertex, LINK_ROWS, ribbonFragment, ribbonVertex } from "./shaders/edge";

export const LINK_CAPACITY = 192;
const SEGMENTS = 22;
const KIND: Record<SceneLink["kind"], number> = { formula: 0, cause: 1, evidence: 2, definition: 3 };
/** CSS pixel widths per kind */
export const WIDTH: Record<SceneLink["kind"], number> = { formula: 1.8, cause: 1.5, evidence: 1.3, definition: 1.1 };
/** flow points per link of each kind */
const FLOW: Record<SceneLink["kind"], number> = { formula: 7, cause: 5, evidence: 3, definition: 0 };

export interface BlockBox {
  center: [number, number, number];
  scale: [number, number, number];
}

export class Edges {
  readonly ribbons: Mesh;
  readonly flow: Points;
  readonly texture: DataTexture;
  readonly data: Float32Array;
  readonly ribbonMaterial: ShaderMaterial;
  readonly flowMaterial: ShaderMaterial;
  count = 0;
  private flowCap = 600;
  private flowUsed = 0;
  private readonly a = new Vector3();
  private readonly b = new Vector3();
  private readonly c = new Vector3();
  private readonly d = new Vector3();

  constructor(env: Env) {
    this.data = new Float32Array(LINK_CAPACITY * LINK_ROWS * 4);
    this.texture = new DataTexture(this.data, LINK_CAPACITY, LINK_ROWS, RGBAFormat, FloatType);
    this.texture.minFilter = NearestFilter;
    this.texture.magFilter = NearestFilter;
    this.texture.generateMipmaps = false;
    this.texture.needsUpdate = true;

    const shared = {
      uTime: env.uTime,
      uFogColor: env.uFogColor,
      uFogNear: env.uFogNear,
      uFogDensity: env.uFogDensity,
      uPixelRatio: env.uPixelRatio,
      uLinks: { value: this.texture },
      uFocusColor: { value: env.uHud.value.clone() },
    };
    this.ribbonMaterial = new ShaderMaterial({
      vertexShader: ribbonVertex,
      fragmentShader: ribbonFragment,
      uniforms: { ...shared, uResolution: env.uResolution, uPulseColor: { value: env.uHud.value.clone() } },
      transparent: true,
      depthWrite: false,
      side: DoubleSide,
    });
    this.ribbons = new Mesh(new BufferGeometry(), this.ribbonMaterial);
    this.ribbons.frustumCulled = false;
    this.ribbons.renderOrder = 3;

    this.flowMaterial = new ShaderMaterial({
      vertexShader: flowVertex,
      fragmentShader: flowFragment,
      uniforms: { ...shared, uFlowOn: { value: 1 } },
      transparent: true,
      depthWrite: false,
    });
    this.flow = new Points(new BufferGeometry(), this.flowMaterial);
    this.flow.frustumCulled = false;
    this.flow.renderOrder = 4;
  }

  /** Rebuilds the geometry for a new set of links (only when the graph's links change). */
  setLinks(links: SceneLink[], box: (id: string) => BlockBox | undefined, flowCap: number): void {
    this.count = Math.min(links.length, LINK_CAPACITY);
    this.flowCap = flowCap;
    for (let i = 0; i < this.count; i++) {
      const link = links[i];
      const from = box(link.source);
      const to = box(link.target);
      if (from && to) this.curve(i, from, to);
      this.row(i, 1)[3] = KIND[link.kind];
      this.row(i, 2)[3] = WIDTH[link.kind];
    }
    this.texture.needsUpdate = true;
    this.buildRibbons();
    this.buildFlow(links);
  }

  /** The texture row `row` of link `i`, as a 4-float view (no allocation: a subarray per call is avoided). */
  row(i: number, row: number): Float32Array {
    const o = (row * LINK_CAPACITY + i) * 4;
    return this.data.subarray(o, o + 4);
  }

  /** Index into `data` of row `row` of link `i`. */
  at(i: number, row: number): number {
    return (row * LINK_CAPACITY + i) * 4;
  }

  /** Control points from the side of the source block facing the target to the facing side of the target. */
  private curve(i: number, from: BlockBox, to: BlockBox): void {
    const [sx, sy, sz] = from.center;
    const [tx, ty, tz] = to.center;
    const dx = tx - sx;
    const dz = tz - sz;
    const p0 = this.a;
    const p3 = this.d;
    const p1 = this.b;
    const p2 = this.c;
    if (Math.abs(dx) > BLOCK[0] * 0.6) {
      const dir = Math.sign(dx);
      p0.set(sx + dir * (BLOCK[0] / 2) * from.scale[0], sy, sz);
      p3.set(tx - dir * (BLOCK[0] / 2) * to.scale[0], ty, tz);
      const k = Math.max(0.5, Math.abs(p3.x - p0.x) * 0.45);
      p1.set(p0.x + dir * k, p0.y, p0.z);
      p2.set(p3.x - dir * k, p3.y, p3.z);
    } else {
      const dir = Math.sign(dz) || 1;
      p0.set(sx, sy, sz + dir * (BLOCK[2] / 2) * from.scale[2]);
      p3.set(tx, ty, tz - dir * (BLOCK[2] / 2) * to.scale[2]);
      const k = Math.max(0.35, Math.abs(p3.z - p0.z) * 0.45);
      p1.set(p0.x, p0.y, p0.z + dir * k);
      p2.set(p3.x, p3.y, p3.z - dir * k);
    }
    const lift = 0.22 + 0.05 * p0.distanceTo(p3);
    p1.y += lift;
    p2.y += lift;
    let length = 0;
    let px = p0.x;
    let py = p0.y;
    let pz = p0.z;
    for (let s = 1; s <= 16; s++) {
      const t = s / 16;
      const u = 1 - t;
      const w0 = u * u * u;
      const w1 = 3 * u * u * t;
      const w2 = 3 * u * t * t;
      const w3 = t * t * t;
      const x = w0 * p0.x + w1 * p1.x + w2 * p2.x + w3 * p3.x;
      const y = w0 * p0.y + w1 * p1.y + w2 * p2.y + w3 * p3.y;
      const z = w0 * p0.z + w1 * p1.z + w2 * p2.z + w3 * p3.z;
      length += Math.hypot(x - px, y - py, z - pz);
      px = x;
      py = y;
      pz = z;
    }
    const d = this.data;
    let o = this.at(i, 0);
    d[o] = p0.x;
    d[o + 1] = p0.y;
    d[o + 2] = p0.z;
    d[o + 3] = length;
    o = this.at(i, 1);
    d[o] = p1.x;
    d[o + 1] = p1.y;
    d[o + 2] = p1.z;
    o = this.at(i, 2);
    d[o] = p2.x;
    d[o + 1] = p2.y;
    d[o + 2] = p2.z;
    o = this.at(i, 3);
    d[o] = p3.x;
    d[o + 1] = p3.y;
    d[o + 2] = p3.z;
  }

  private buildRibbons(): void {
    const quads = this.count * SEGMENTS;
    const seg = new Float32Array(quads * 4 * 3);
    const corner = new Float32Array(quads * 4 * 2);
    const index = new Uint32Array(quads * 6);
    let q = 0;
    for (let i = 0; i < this.count; i++) {
      for (let s = 0; s < SEGMENTS; s++, q++) {
        const t0 = s / SEGMENTS;
        const t1 = (s + 1) / SEGMENTS;
        for (let v = 0; v < 4; v++) {
          const o = (q * 4 + v) * 3;
          seg[o] = i;
          seg[o + 1] = t0;
          seg[o + 2] = t1;
          const c = (q * 4 + v) * 2;
          corner[c] = v % 2 === 0 ? -1 : 1;
          corner[c + 1] = v < 2 ? 0 : 1;
        }
        const base = q * 4;
        const o = q * 6;
        index[o] = base;
        index[o + 1] = base + 1;
        index[o + 2] = base + 2;
        index[o + 3] = base + 2;
        index[o + 4] = base + 1;
        index[o + 5] = base + 3;
      }
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute("aSeg", new BufferAttribute(seg, 3));
    geometry.setAttribute("aCorner", new BufferAttribute(corner, 2));
    // three.js needs a position attribute to know the vertex count; the shader computes the real position
    geometry.setAttribute("position", new BufferAttribute(new Float32Array(quads * 4 * 3), 3));
    geometry.setIndex(new BufferAttribute(index, 1));
    this.ribbons.geometry.dispose();
    this.ribbons.geometry = geometry;
  }

  private buildFlow(links: SceneLink[]): void {
    let total = 0;
    for (let i = 0; i < this.count; i++) total += FLOW[links[i].kind];
    const n = Math.min(total, 600);
    const flow = new Float32Array(n * 3);
    let k = 0;
    for (let i = 0; i < this.count && k < n; i++) {
      const per = FLOW[links[i].kind];
      for (let j = 0; j < per && k < n; j++, k++) {
        flow[k * 3] = i;
        flow[k * 3 + 1] = (j + hash(i * 13.7 + j) * 0.6) / per;
        flow[k * 3 + 2] = links[i].kind === "formula" ? 0.55 : 0.35;
      }
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute("aFlow", new BufferAttribute(flow, 3));
    geometry.setAttribute("position", new BufferAttribute(new Float32Array(n * 3), 3));
    this.flow.geometry.dispose();
    this.flow.geometry = geometry;
    this.flowUsed = n;
    this.setFlowCap(this.flowCap);
  }

  /** At most `cap` flow points are drawn (quality tier). */
  setFlowCap(cap: number): void {
    this.flowCap = cap;
    this.flow.geometry.setDrawRange(0, Math.min(this.flowUsed, cap));
  }

  commit(): void {
    this.texture.needsUpdate = true;
  }

  dispose(): void {
    this.ribbons.geometry.dispose();
    this.flow.geometry.dispose();
    this.ribbonMaterial.dispose();
    this.flowMaterial.dispose();
    this.texture.dispose();
  }
}

function hash(x: number): number {
  const s = Math.sin(x * 127.1) * 43758.5453;
  return s - Math.floor(s);
}
