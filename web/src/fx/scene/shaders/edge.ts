// Edges (A9): every link is a cubic curve whose control points and live state sit in one small float texture.
// The ribbon shader draws each curve as screen-space quads of an exact pixel width; the flow shader moves points
// along the same curves. Rows of the texture, one column per link:
//   0  p0.xyz, arc length        1  p1.xyz, kind (0 formula, 1 cause, 2 evidence, 3 definition)
//   2  p2.xyz, width (CSS px)    3  p3.xyz, reveal (0 to 1, drawn from source to target)
//   4  color.rgb (linear), alpha 5  focus, test-pulse start, broken, dashed (proposed)

import { FOG, FOG_UNIFORMS, NOISE } from "./common";

export const LINK_ROWS = 6;

const LINK_FETCH = /* glsl */ `
uniform sampler2D uLinks;

vec4 linkRow(int i, int row) {
  return texelFetch(uLinks, ivec2(i, row), 0);
}

vec3 bezier(vec3 a, vec3 b, vec3 c, vec3 d, float t) {
  float u = 1.0 - t;
  return u * u * u * a + 3.0 * u * u * t * b + 3.0 * u * t * t * c + t * t * t * d;
}
`;

export const ribbonVertex = /* glsl */ `
attribute vec3 aSeg;     // link, t at the start, t at the end
attribute vec2 aCorner;  // side (-1 or 1), end (0 or 1)
uniform vec2 uResolution;
uniform float uPixelRatio;

varying float vT;
varying float vSide;
varying float vWidth;
varying float vFull;
varying float vLen;
varying float vReveal;
varying float vLink;
varying float vDashed;
varying vec4 vColor;
varying vec4 vInfo;
varying vec3 vWorld;

${LINK_FETCH}

void main() {
  int i = int(aSeg.x + 0.5);
  vec4 r0 = linkRow(i, 0);
  vec4 r1 = linkRow(i, 1);
  vec4 r2 = linkRow(i, 2);
  vec4 r3 = linkRow(i, 3);
  vec4 r4 = linkRow(i, 4);
  vec4 r5 = linkRow(i, 5);
  vec3 a = bezier(r0.xyz, r1.xyz, r2.xyz, r3.xyz, aSeg.y);
  vec3 b = bezier(r0.xyz, r1.xyz, r2.xyz, r3.xyz, aSeg.z);
  vec4 ca = projectionMatrix * viewMatrix * vec4(a, 1.0);
  vec4 cb = projectionMatrix * viewMatrix * vec4(b, 1.0);
  vec2 half_ = uResolution * 0.5;
  vec2 sa = ca.xy / ca.w * half_;
  vec2 sb = cb.xy / cb.w * half_;
  vec2 dir = sb - sa;
  float len = length(dir);
  dir = len > 1e-4 ? dir / len : vec2(1.0, 0.0);
  vec2 nrm = vec2(-dir.y, dir.x);
  float focus = r5.x;
  float width = (r2.w + focus * 1.1) * uPixelRatio;
  float full = width + 2.0;
  vec4 c = aCorner.y < 0.5 ? ca : cb;
  c.xy += nrm * aCorner.x * (full * 0.5) / half_ * c.w;
  gl_Position = c;

  vT = mix(aSeg.y, aSeg.z, aCorner.y);
  vSide = aCorner.x;
  vWidth = width;
  vFull = full;
  vLen = r0.w;
  vReveal = r3.w;
  vLink = aSeg.x;
  vDashed = r5.w;
  vColor = r4;
  vInfo = vec4(r1.w, focus, r5.y, r5.z);
  vWorld = aCorner.y < 0.5 ? a : b;
}
`;

export const ribbonFragment = /* glsl */ `
uniform float uTime;
uniform vec3 uFocusColor;
uniform vec3 uPulseColor;
${FOG_UNIFORMS}

varying float vT;
varying float vSide;
varying float vWidth;
varying float vFull;
varying float vLen;
varying float vReveal;
varying float vLink;
varying float vDashed;
varying vec4 vColor;
varying vec4 vInfo;
varying vec3 vWorld;

${NOISE}
${FOG}

float dashes(float s, float period, float duty, float fw) {
  float f = fract(s / period);
  float w = max(fw / period, 1e-4);
  return 1.0 - smoothstep(duty - w, duty + w, f);
}

void main() {
  if (vT > vReveal) discard;
  float d = abs(vSide) * vFull * 0.5;
  float cover = clamp(vWidth * 0.5 + 0.5 - d, 0.0, 1.0) * min(vWidth, 1.0);
  float s = vT * vLen;
  float fw = fwidth(s);
  float kind = vInfo.x;
  float focus = vInfo.y;
  float dash = 1.0;
  if (kind > 0.5 && kind < 1.5) dash = dashes(s, 0.46, 0.56, fw);
  else if (kind > 1.5 && kind < 2.5) dash = dashes(s, 0.2, 0.34, fw);
  else if (kind > 2.5) dash = dashes(s, 0.26, 0.4, fw);
  if (vDashed > 0.5) dash = min(dash, dashes(s, 0.3, 0.42, fw));
  dash = mix(dash, dashes(s - uTime * 1.6, 0.5, 0.64, fw), focus);

  vec3 col = mix(vColor.rgb, uFocusColor * 1.25, focus);
  float alpha = mix(vColor.a, 1.0, focus);

  float p = (uTime - vInfo.z) / 0.9;
  float pulse = (p > 0.0 && p < 1.25) ? exp(-pow((vT - p) * 6.5, 2.0)) : 0.0;
  col = mix(col, uPulseColor * 2.2, pulse * 0.9);
  alpha = max(alpha, pulse);
  dash = max(dash, pulse);

  if (vInfo.w > 0.5) {
    float flick = step(0.32, hash11(floor(uTime * 13.0) + vLink * 7.13));
    float gap = step(0.34, fract(s / 0.31 + hash11(vLink)));
    alpha *= mix(0.25, 1.0, flick) * gap;
  }

  alpha *= 1.0 - fogAmount(length(vWorld - cameraPosition));
  gl_FragColor = vec4(col, alpha * cover * dash);
}
`;

export const flowVertex = /* glsl */ `
attribute vec3 aFlow;  // link, phase, speed (world units per second)
uniform float uTime;
uniform float uPixelRatio;
uniform float uFlowOn;
uniform vec3 uFocusColor;
${FOG_UNIFORMS}
varying vec3 vColor;
varying float vAlpha;

${LINK_FETCH}
${FOG}

void main() {
  int i = int(aFlow.x + 0.5);
  vec4 r0 = linkRow(i, 0);
  vec4 r1 = linkRow(i, 1);
  vec4 r2 = linkRow(i, 2);
  vec4 r3 = linkRow(i, 3);
  vec4 r4 = linkRow(i, 4);
  vec4 r5 = linkRow(i, 5);
  float focus = r5.x;
  float len = max(r0.w, 0.5);
  float t = fract(aFlow.y + uTime * aFlow.z * (1.0 + 1.6 * focus) / len);
  vec3 p = bezier(r0.xyz, r1.xyz, r2.xyz, r3.xyz, t);
  gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
  float ends = smoothstep(0.0, 0.12, t) * (1.0 - smoothstep(0.85, 1.0, t));
  vAlpha = mix(r4.a, 1.0, focus) * step(0.999, r3.w) * ends * (1.0 - r5.z) * uFlowOn;
  vAlpha *= 1.0 - fogAmount(length(p - cameraPosition));
  vColor = mix(r4.rgb, uFocusColor, focus) * 1.5;
  gl_PointSize = (2.6 + 1.8 * focus) * uPixelRatio;
}
`;

export const flowFragment = /* glsl */ `
varying vec3 vColor;
varying float vAlpha;

void main() {
  float r = length(gl_PointCoord - 0.5);
  float a = vAlpha * (1.0 - smoothstep(0.2, 0.5, r));
  if (a < 0.003) discard;
  gl_FragColor = vec4(vColor, a);
}
`;
