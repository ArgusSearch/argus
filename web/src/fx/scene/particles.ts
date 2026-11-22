// Snow (A10) in two depths with a pointer wake (A21), and one pooled point burst system for the ice shards of
// an alarm crack (A15) and the motes that converge into a block while it materializes (A2, A16).
// All motion is computed in the vertex shaders from the time uniform.

import {
  BufferAttribute,
  BufferGeometry,
  Color,
  DynamicDrawUsage,
  Points,
  ShaderMaterial,
  Vector2,
  Vector3,
} from "three";
import type { Env } from "./env";
import { FOG, FOG_UNIFORMS } from "./shaders/common";

export const SNOW_CAPACITY = 1400;
export const BURST_CAPACITY = 600;

const snowVertex = /* glsl */ `
attribute vec4 aSeed;   // xyz position in the box (0 to 1), w size and speed
attribute float aLayer; // 0 far, 1 near
uniform float uTime;
uniform float uPixelRatio;
uniform vec2 uResolution;
uniform vec3 uCenter;
uniform vec3 uBox;
uniform vec3 uNearCenter;
uniform vec3 uNearBox;
uniform vec2 uPointer;
uniform float uPointerOn;
${FOG_UNIFORMS}
varying float vAlpha;
varying float vSoft;

${FOG}

void main() {
  bool near = aLayer > 0.5;
  vec3 box = near ? uNearBox : uBox;
  vec3 center = near ? uNearCenter : uCenter;
  vec3 p = aSeed.xyz * box;
  float t = uTime;
  p.y -= (0.28 + 0.35 * aSeed.w) * t;
  p.x += 0.12 * t + sin(t * 0.31 + aSeed.y * 41.0) * 0.55;
  p.z += cos(t * 0.23 + aSeed.x * 29.0) * 0.4;
  p = mod(p - center + box * 0.5, box) - box * 0.5 + center;

  vec4 mv = viewMatrix * vec4(p, 1.0);
  vec4 clip = projectionMatrix * mv;
  // the pointer pushes flakes aside on screen
  vec2 ndc = clip.xy / clip.w;
  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 away = (ndc - uPointer) * aspect;
  float dist = length(away);
  float push = uPointerOn * (1.0 - smoothstep(0.0, 0.22, dist)) * 0.07;
  ndc += dist > 1e-4 ? away / dist / aspect * push : vec2(0.0);
  clip.xy = ndc * clip.w;
  gl_Position = clip;

  float size = near ? 0.09 + 0.07 * aSeed.w : 0.032 + 0.028 * aSeed.w;
  float px = size * projectionMatrix[1][1] * uResolution.y * 0.5 / max(-mv.z, 0.1);
  gl_PointSize = clamp(px, 1.0, 64.0 * uPixelRatio);
  vAlpha = (near ? 0.38 : 1.0) * (1.0 - fogAmount(-mv.z) * 0.85);
  vSoft = near ? 0.05 : 0.22;
}
`;

const snowFragment = /* glsl */ `
uniform vec3 uSnow;
uniform float uSnowAlpha;
varying float vAlpha;
varying float vSoft;

void main() {
  float r = length(gl_PointCoord - 0.5);
  float a = (1.0 - smoothstep(vSoft, 0.5, r)) * vAlpha * uSnowAlpha;
  if (a < 0.004) discard;
  gl_FragColor = vec4(uSnow, a);
}
`;

const burstVertex = /* glsl */ `
attribute vec3 aOrigin;
attribute vec3 aVelocity;
attribute vec4 aLife;   // x birth, y life, z gravity, w size (world units)
attribute vec3 aColor;
uniform float uTime;
uniform vec2 uResolution;
${FOG_UNIFORMS}
varying vec3 vColor;
varying float vAlpha;

${FOG}

void main() {
  float age = uTime - aLife.x;
  if (age < 0.0 || age > aLife.y) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 0.0;
    vAlpha = 0.0;
    return;
  }
  float k = 1.6;
  vec3 drift = aVelocity * (1.0 - exp(-k * age)) / k;
  vec3 p = aOrigin + drift + vec3(0.0, -0.5 * aLife.z * age * age, 0.0);
  p.y = max(p.y, 0.02);
  vec4 mv = viewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  float u = age / aLife.y;
  float px = aLife.w * projectionMatrix[1][1] * uResolution.y * 0.5 / max(-mv.z, 0.1);
  gl_PointSize = clamp(px, 1.5, 24.0);
  vAlpha = (1.0 - u * u) * smoothstep(0.0, 0.05, age) * (1.0 - fogAmount(-mv.z));
  vColor = aColor;
}
`;

const burstFragment = /* glsl */ `
varying vec3 vColor;
varying float vAlpha;

void main() {
  vec2 q = abs(gl_PointCoord - 0.5);
  // small diamond: reads as a shard, not a dot
  float d = q.x + q.y;
  float a = vAlpha * (1.0 - smoothstep(0.3, 0.5, d));
  if (a < 0.004) discard;
  gl_FragColor = vec4(vColor, a);
}
`;

export class Snow {
  readonly points: Points;
  readonly material: ShaderMaterial;
  private readonly layer: Float32Array;

  constructor(env: Env) {
    const seeds = new Float32Array(SNOW_CAPACITY * 4);
    const layer = new Float32Array(SNOW_CAPACITY);
    for (let i = 0; i < SNOW_CAPACITY; i++) {
      seeds[i * 4] = Math.random();
      seeds[i * 4 + 1] = Math.random();
      seeds[i * 4 + 2] = Math.random();
      seeds[i * 4 + 3] = Math.random();
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute("aSeed", new BufferAttribute(seeds, 4));
    geometry.setAttribute("aLayer", new BufferAttribute(layer, 1));
    geometry.setAttribute("position", new BufferAttribute(new Float32Array(SNOW_CAPACITY * 3), 3));
    this.layer = layer;
    this.material = new ShaderMaterial({
      vertexShader: snowVertex,
      fragmentShader: snowFragment,
      uniforms: {
        uTime: env.uTime,
        uPixelRatio: env.uPixelRatio,
        uResolution: env.uResolution,
        uFogColor: env.uFogColor,
        uFogNear: env.uFogNear,
        uFogDensity: env.uFogDensity,
        uCenter: { value: new Vector3() },
        uBox: { value: new Vector3(46, 22, 40) },
        uNearCenter: { value: new Vector3() },
        uNearBox: { value: new Vector3(16, 10, 10) },
        uPointer: { value: new Vector2(9, 9) },
        uPointerOn: { value: 0 },
        uSnow: { value: new Color("#ffffff") },
        uSnowAlpha: { value: 0.55 },
      },
      transparent: true,
      depthWrite: false,
    });
    this.points = new Points(geometry, this.material);
    this.points.frustumCulled = false;
    this.points.renderOrder = 6;
  }

  /** Draws `far` distant flakes and `near` large soft ones in front of the graph. */
  setCounts(far: number, near: number): void {
    const n = Math.min(far + near, SNOW_CAPACITY);
    for (let i = 0; i < n; i++) this.layer[i] = i < near ? 1 : 0;
    (this.points.geometry.getAttribute("aLayer") as BufferAttribute).needsUpdate = true;
    this.points.geometry.setDrawRange(0, n);
  }

  get uniforms() {
    return this.material.uniforms as {
      uCenter: { value: Vector3 };
      uNearCenter: { value: Vector3 };
      uPointer: { value: Vector2 };
      uPointerOn: { value: number };
      uSnow: { value: Color };
      uSnowAlpha: { value: number };
    };
  }

  dispose(): void {
    this.points.geometry.dispose();
    this.material.dispose();
  }
}

export class Bursts {
  readonly points: Points;
  readonly material: ShaderMaterial;
  private readonly origin: Float32Array;
  private readonly velocity: Float32Array;
  private readonly life: Float32Array;
  private readonly color: Float32Array;
  private next = 0;
  private dirty = false;

  constructor(env: Env) {
    this.origin = new Float32Array(BURST_CAPACITY * 3);
    this.velocity = new Float32Array(BURST_CAPACITY * 3);
    this.life = new Float32Array(BURST_CAPACITY * 4);
    this.color = new Float32Array(BURST_CAPACITY * 3);
    for (let i = 0; i < BURST_CAPACITY; i++) this.life[i * 4] = -1000;
    const geometry = new BufferGeometry();
    geometry.setAttribute("aOrigin", new BufferAttribute(this.origin, 3).setUsage(DynamicDrawUsage));
    geometry.setAttribute("aVelocity", new BufferAttribute(this.velocity, 3).setUsage(DynamicDrawUsage));
    geometry.setAttribute("aLife", new BufferAttribute(this.life, 4).setUsage(DynamicDrawUsage));
    geometry.setAttribute("aColor", new BufferAttribute(this.color, 3).setUsage(DynamicDrawUsage));
    geometry.setAttribute("position", new BufferAttribute(new Float32Array(BURST_CAPACITY * 3), 3));
    this.material = new ShaderMaterial({
      vertexShader: burstVertex,
      fragmentShader: burstFragment,
      uniforms: {
        uTime: env.uTime,
        uResolution: env.uResolution,
        uFogColor: env.uFogColor,
        uFogNear: env.uFogNear,
        uFogDensity: env.uFogDensity,
      },
      transparent: true,
      depthWrite: false,
    });
    this.points = new Points(geometry, this.material);
    this.points.frustumCulled = false;
    this.points.renderOrder = 5;
  }

  /** Ice shards thrown from a cracking block centered at `x, y, z`. */
  shards(x: number, y: number, z: number, time: number, n: number, tint: Color, white: Color): void {
    for (let k = 0; k < n; k++) {
      const a = Math.random() * Math.PI * 2;
      const up = 0.35 + Math.random() * 0.9;
      const speed = 1.4 + Math.random() * 3.2;
      const c = Math.random() < 0.55 ? tint : white;
      const bright = 1.2 + Math.random() * 0.8;
      this.emit(
        x + (Math.random() - 0.5) * 2.2,
        y + (Math.random() - 0.2) * 0.4,
        z + (Math.random() - 0.5) * 0.7,
        Math.cos(a) * speed,
        up * speed,
        Math.sin(a) * speed * 0.6,
        time + Math.random() * 0.06,
        0.9 + Math.random() * 0.9,
        4.5,
        0.05 + Math.random() * 0.05,
        c.r * bright,
        c.g * bright,
        c.b * bright,
      );
    }
  }

  /** Motes that drift in from around a block and arrive as it freezes solid. */
  motes(x: number, y: number, z: number, start: number, duration: number, n: number, c: Color): void {
    const k = 1.6;
    const reach = (1 - Math.exp(-k * duration)) / k;
    for (let m = 0; m < n; m++) {
      const a = Math.random() * Math.PI * 2;
      const r = 1.2 + Math.random() * 1.8;
      const ox = Math.cos(a) * r;
      const oz = Math.sin(a) * r * 0.6;
      const oy = 0.3 + Math.random() * 1.6;
      this.emit(x + ox, y + oy, z + oz, -ox / reach, -oy / reach, -oz / reach, start + Math.random() * 0.2, duration, 0, 0.035 + Math.random() * 0.03, c.r, c.g, c.b);
    }
  }

  private emit(
    x: number,
    y: number,
    z: number,
    vx: number,
    vy: number,
    vz: number,
    birth: number,
    life: number,
    gravity: number,
    size: number,
    r: number,
    g: number,
    b: number,
  ): void {
    const i = this.next;
    this.next = (this.next + 1) % BURST_CAPACITY;
    const o = i * 3;
    const l = i * 4;
    this.origin[o] = x;
    this.origin[o + 1] = y;
    this.origin[o + 2] = z;
    this.velocity[o] = vx;
    this.velocity[o + 1] = vy;
    this.velocity[o + 2] = vz;
    this.color[o] = r;
    this.color[o + 1] = g;
    this.color[o + 2] = b;
    this.life[l] = birth;
    this.life[l + 1] = life;
    this.life[l + 2] = gravity;
    this.life[l + 3] = size;
    this.dirty = true;
  }

  commit(): void {
    if (!this.dirty) return;
    this.dirty = false;
    const g = this.points.geometry;
    for (const name of ["aOrigin", "aVelocity", "aLife", "aColor"]) (g.getAttribute(name) as BufferAttribute).needsUpdate = true;
  }

  dispose(): void {
    this.points.geometry.dispose();
    this.material.dispose();
  }
}
