// The ground (A11): a pale plane that fades into the fog, a faint dot grid, concentric rings around whatever
// Argus is checking, and expanding pulses for the hourly tick (A17), an alarm (A15) and a freeze-in (A16).

import { Color, Mesh, PlaneGeometry, ShaderMaterial, Vector2, Vector4 } from "three";
import type { Env } from "./env";
import { FOG, FOG_UNIFORMS } from "./shaders/common";

export const PULSES = 4;

export type PulseKind = "tick" | "alarm" | "freeze";
const PULSE_KIND: Record<PulseKind, number> = { tick: 1, alarm: 2, freeze: 3 };

const vertex = /* glsl */ `
varying vec3 vWorld;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vWorld = world.xyz;
  gl_Position = projectionMatrix * viewMatrix * world;
}
`;

const fragment = /* glsl */ `
uniform float uTime;
uniform vec3 uGround;
uniform vec3 uHud;
uniform vec2 uCenter;
uniform float uRadius;
uniform vec2 uRingCenter;
uniform float uRings;
uniform vec4 uPulses[${PULSES}];
uniform vec3 uPulseColors[${PULSES}];
${FOG_UNIFORMS}
varying vec3 vWorld;

${FOG}

void main() {
  vec2 p = vWorld.xz;
  float r0 = length((p - uCenter) * vec2(0.8, 1.0)) / uRadius;
  vec3 col = mix(uGround, uFogColor, smoothstep(0.55, 1.7, r0));

  // dot grid
  vec2 cell = fract(p / 0.92) - 0.5;
  float dd = length(cell) * 0.92;
  float fw = fwidth(dd);
  float dots = 1.0 - smoothstep(0.024 - fw, 0.024 + fw, dd);
  col = mix(col, uHud, dots * 0.2 * (1.0 - smoothstep(0.35, 1.25, r0)));

  // rings around the focus, drifting slowly outward
  float rr = length(p - uRingCenter);
  float phase = rr / 1.05 - uTime * 0.11;
  float ring = abs(fract(phase) - 0.5) * 1.05;
  float fr = fwidth(rr);
  float lines = 1.0 - smoothstep(0.006, 0.006 + fr * 1.4, ring);
  float reach = smoothstep(1.1, 1.8, rr) * (1.0 - smoothstep(2.2, 5.2, rr));
  col = mix(col, uHud, lines * reach * uRings * 0.3);

  for (int i = 0; i < ${PULSES}; i++) {
    vec4 pu = uPulses[i];
    if (pu.w < 0.5) continue;
    float age = uTime - pu.z;
    if (age < 0.0) continue;
    bool tick = pu.w < 1.5;
    float speed = tick ? 7.5 : (pu.w < 2.5 ? 11.0 : 7.0);
    float life = tick ? 2.8 : (pu.w < 2.5 ? 1.0 : 1.5);
    if (age > life) continue;
    float radius = age * speed;
    float width = 0.05 + age * (tick ? 0.18 : 0.35);
    float dist = abs(length(p - pu.xy) - radius);
    float a = (1.0 - smoothstep(0.0, width, dist)) * pow(1.0 - age / life, 1.5);
    float strength = tick ? 0.3 : 0.85;
    col = mix(col, uPulseColors[i], a * strength);
  }

  col = mix(col, uFogColor, fogAmount(length(vWorld - cameraPosition)));
  gl_FragColor = vec4(col, 1.0);
}
`;

export class Ground {
  readonly mesh: Mesh;
  readonly material: ShaderMaterial;
  private readonly pulses: Vector4[];
  private readonly colors: Color[];
  private next = 0;

  constructor(env: Env) {
    this.pulses = Array.from({ length: PULSES }, () => new Vector4(0, 0, -100, 0));
    this.colors = Array.from({ length: PULSES }, () => new Color());
    this.material = new ShaderMaterial({
      vertexShader: vertex,
      fragmentShader: fragment,
      uniforms: {
        uTime: env.uTime,
        uHud: env.uHud,
        uFogColor: env.uFogColor,
        uFogNear: env.uFogNear,
        uFogDensity: env.uFogDensity,
        uGround: { value: env.uFogColor.value.clone() },
        uCenter: { value: new Vector2() },
        uRadius: { value: 14 },
        uRingCenter: { value: new Vector2() },
        uRings: { value: 0 },
        uPulses: { value: this.pulses },
        uPulseColors: { value: this.colors },
      },
    });
    this.mesh = new Mesh(new PlaneGeometry(320, 320).rotateX(-Math.PI / 2), this.material);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 0;
  }

  get uniforms() {
    return this.material.uniforms as {
      uGround: { value: Color };
      uCenter: { value: Vector2 };
      uRadius: { value: number };
      uRingCenter: { value: Vector2 };
      uRings: { value: number };
    };
  }

  /** Starts a ring pulse at `x, z`; the oldest of the four slots is reused. */
  pulse(kind: PulseKind, x: number, z: number, time: number, color: Color): void {
    const slot = this.pulses[this.next];
    slot.set(x, z, time, PULSE_KIND[kind]);
    this.colors[this.next].copy(color);
    this.next = (this.next + 1) % PULSES;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.material.dispose();
  }
}
