// The ice block (A8): frosted surface with wrap lighting, a bright fresnel rim and a core light whose color and
// strength carry the metric's state. The same shader draws the materialize cage (A2, A16) and the crack (A15).

import { FOG, FOG_UNIFORMS, NOISE } from "./common";

export const blockVertex = /* glsl */ `
attribute vec3 aCore;
attribute vec4 aState;   // x glow, y crack, z materialize, w dim
attribute vec4 aState2;  // x highlight, y refreeze flash, z seed, w log

varying vec3 vLocal;
varying vec3 vWorld;
varying vec3 vNormalW;
varying vec3 vScale;
varying vec3 vCore;
varying vec4 vState;
varying vec4 vState2;

void main() {
  vec4 world = modelMatrix * instanceMatrix * vec4(position, 1.0);
  vec3 scale = vec3(length(instanceMatrix[0].xyz), length(instanceMatrix[1].xyz), length(instanceMatrix[2].xyz));
  vLocal = position;
  vWorld = world.xyz;
  vNormalW = normalize(normal / scale);
  vScale = scale;
  vCore = aCore;
  vState = aState;
  vState2 = aState2;
  gl_Position = projectionMatrix * viewMatrix * world;
}
`;

export const blockFragment = /* glsl */ `
uniform vec3 uHalf;
uniform vec3 uLit;
uniform vec3 uShade;
uniform vec3 uRim;
uniform vec3 uHud;
uniform vec3 uLightDir;
uniform float uTime;
${FOG_UNIFORMS}

varying vec3 vLocal;
varying vec3 vWorld;
varying vec3 vNormalW;
varying vec3 vScale;
varying vec3 vCore;
varying vec4 vState;
varying vec4 vState2;

${NOISE}
${FOG}

void main() {
  float seed = vState2.z;
  float m = vState.z;

  // materialize: a cage of the block's edges draws in, then the solid ice freezes in behind a bright front
  vec3 d = uHalf - abs(vLocal);
  float lo = min(d.x, min(d.y, d.z));
  float hi = max(d.x, max(d.y, d.z));
  float mid = d.x + d.y + d.z - lo - hi;
  float edge = 1.0 - smoothstep(0.012, 0.045, mid);
  float cage = smoothstep(0.0, 0.2, m) * (1.0 - smoothstep(0.7, 1.0, m));
  float fill = clamp((m - 0.28) / 0.62, 0.0, 1.0);
  float n = vnoise(vLocal * vec3(1.7, 5.0, 4.0) + seed * 17.0) * 0.8 + (vLocal.x / uHalf.x * 0.5 + 0.5) * 0.2;
  float threshold = fill * 1.04;
  float solid = step(n, threshold);
  if (solid < 0.5 && edge * cage < 0.03) discard;
  float front = (1.0 - smoothstep(0.0, 0.06, threshold - n)) * solid * (1.0 - step(1.0, fill));

  vec3 N = normalize(vNormalW);
  vec3 V = normalize(cameraPosition - vWorld);
  float ndl = dot(N, uLightDir);
  float wrap = clamp((ndl + 0.6) / 1.6, 0.0, 1.0);
  float frost = fbm3(vLocal * vec3(2.4, 7.0, 5.5) + seed * 7.0);
  vec3 base = mix(uShade, uLit, wrap);
  base *= 0.9 + 0.18 * frost;
  base = mix(base, uLit * 1.05, smoothstep(0.7, 0.98, N.y) * 0.3);

  float facing = clamp(dot(N, V), 0.0, 1.0);
  float fres = pow(1.0 - facing, 3.0);

  // the light inside: how close the view ray passes the block's center, in the block's own proportions
  vec3 q = vLocal / uHalf;
  vec3 ray = normalize(-V / vScale / uHalf);
  vec3 closest = q - ray * dot(q, ray);
  float core = exp(-dot(closest, closest) * 2.2);

  float glow = vState.x;
  float dim = vState.w;
  vec3 col = base * (1.0 - 0.38 * dim);
  col += vCore * glow * (0.85 * core + 0.18);
  col += uRim * fres * (0.5 + 0.9 * vState2.x) * (1.0 - 0.5 * dim);

  float crack = vState.y;
  if (crack > 0.001) {
    float cn = fbm3(vLocal * vec3(1.3, 3.2, 2.6) + seed * 3.0);
    float lines = 1.0 - smoothstep(0.0, 0.012 + 0.03 * crack, abs(cn - 0.5));
    float spread = smoothstep(1.0 - crack, 1.0 - crack + 0.25, vnoise(vLocal * 1.1 + seed * 5.0 + 3.0) * 0.6 + 0.4);
    col *= 1.0 - 0.3 * crack;
    col += vCore * lines * spread * (2.6 + 1.2 * sin(uTime * 7.0 + seed * 20.0) * crack);
  }

  col += uRim * vState2.y * (0.6 + 1.4 * fres);
  col = mix(col, uHud * 1.8, edge * cage * (1.0 - solid));
  col += uHud * front * 1.4;

  col = mix(col, uFogColor, fogAmount(length(vWorld - cameraPosition)));
  gl_FragColor = vec4(col, 1.0);
}
`;

/** The soft shadow under each block, tinted by its core light: the ground under an alarm glows red. */
export const shadowVertex = /* glsl */ `
attribute vec3 aCore;
attribute vec4 aState;
varying vec2 vUv;
varying vec3 vWorld;
varying vec3 vCore;
varying vec4 vState;

void main() {
  vUv = uv;
  vCore = aCore;
  vState = aState;
  vec4 world = modelMatrix * instanceMatrix * vec4(position, 1.0);
  vWorld = world.xyz;
  gl_Position = projectionMatrix * viewMatrix * world;
}
`;

export const shadowFragment = /* glsl */ `
uniform vec3 uShadow;
uniform float uShadowAlpha;
${FOG_UNIFORMS}
varying vec2 vUv;
varying vec3 vWorld;
varying vec3 vCore;
varying vec4 vState;

${FOG}

void main() {
  vec2 p = abs(vUv - 0.5) * 2.0;
  // a soft rounded rectangle: dense right under the block, fading well before the quad's edge
  vec2 inner = vec2(0.5, 0.22);
  vec2 q = max(p - inner, 0.0) / (vec2(1.0) - inner);
  float r = length(q);
  float shade = exp(-r * r * 4.0) * (1.0 - smoothstep(0.75, 1.0, r)) * smoothstep(0.0, 1.0, vState.z);
  float pool = (1.0 - smoothstep(0.0, 1.1, length(p * vec2(0.9, 1.0)))) * vState.x * smoothstep(0.3, 1.0, vState.z);
  float keep = 1.0 - fogAmount(length(vWorld - cameraPosition));
  float a = shade * uShadowAlpha * keep;
  vec3 light = vCore * pool * 0.55 * keep;
  // premultiplied: darkens toward the shadow color, adds the core light
  gl_FragColor = vec4(uShadow * a + light, a);
}
`;
