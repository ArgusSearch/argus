// Post-processing: the scene renders into one multisampled half-float buffer, bloom (A14) adds its glow into it,
// and one final pass maps it to the screen with the camera-speed color fringe (A13), a soft highlight roll-off,
// sRGB encoding and a one-step dither against banding in the fog.

import {
  HalfFloatType,
  LinearFilter,
  ShaderMaterial,
  Vector2,
  WebGLRenderTarget,
  type Camera,
  type Scene,
  type WebGLRenderer,
} from "three";
import { FullScreenQuad } from "three/addons/postprocessing/Pass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

const finalVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const finalFragment = /* glsl */ `
uniform sampler2D tScene;
uniform vec2 uResolution;
uniform float uFringe;
uniform float uTime;
varying vec2 vUv;

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

vec3 rolloff(vec3 x) {
  const float k = 0.8;
  vec3 over = k + (1.0 - k) * (1.0 - exp(-(x - k) / (1.0 - k)));
  return mix(x, over, step(k, x));
}

vec3 toSRGB(vec3 c) {
  return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}

void main() {
  vec3 col;
  if (uFringe > 0.05) {
    vec2 off = (vUv - 0.5) * 2.0 * uFringe / uResolution;
    col.r = texture2D(tScene, vUv + off).r;
    col.g = texture2D(tScene, vUv).g;
    col.b = texture2D(tScene, vUv - off).b;
  } else {
    col = texture2D(tScene, vUv).rgb;
  }
  col = toSRGB(clamp(rolloff(max(col, 0.0)), 0.0, 1.0));
  col += (hash12(gl_FragCoord.xy + fract(uTime * 7.31) * 113.0) - 0.5) / 255.0;
  gl_FragColor = vec4(col, 1.0);
}
`;

export class Post {
  readonly target: WebGLRenderTarget;
  readonly bloom: UnrealBloomPass;
  readonly final: ShaderMaterial;
  private readonly quad: FullScreenQuad;
  bloomOn = true;
  private width = 1;
  private height = 1;

  constructor(samples: number) {
    this.target = new WebGLRenderTarget(1, 1, { type: HalfFloatType, samples, depthBuffer: true, stencilBuffer: false });
    this.target.texture.minFilter = LinearFilter;
    this.target.texture.magFilter = LinearFilter;
    this.target.texture.generateMipmaps = false;
    this.bloom = new UnrealBloomPass(new Vector2(1, 1), 0.7, 0.85, 0.9);
    (this.bloom.highPassUniforms as Record<string, { value: number }>).smoothWidth.value = 0.35;
    this.final = new ShaderMaterial({
      vertexShader: finalVertex,
      fragmentShader: finalFragment,
      uniforms: {
        tScene: { value: this.target.texture },
        uResolution: { value: new Vector2(1, 1) },
        uFringe: { value: 0 },
        uTime: { value: 0 },
      },
      depthTest: false,
      depthWrite: false,
    });
    this.quad = new FullScreenQuad(this.final);
  }

  /** Sizes in drawing-buffer pixels. */
  setSize(width: number, height: number): void {
    if (width === this.width && height === this.height) return;
    this.width = width;
    this.height = height;
    this.target.setSize(width, height);
    this.bloom.setSize(width, height);
    (this.final.uniforms.uResolution.value as Vector2).set(width, height);
  }

  setSamples(samples: number): void {
    if (this.target.samples === samples) return;
    this.target.samples = samples;
    this.target.dispose();
  }

  render(renderer: WebGLRenderer, scene: Scene, camera: Camera, fringe: number, time: number): void {
    renderer.setRenderTarget(this.target);
    renderer.clear(true, true, false);
    renderer.render(scene, camera);
    if (this.bloomOn) this.bloom.render(renderer, null as never, this.target, 0, false);
    this.final.uniforms.uFringe.value = fringe;
    this.final.uniforms.uTime.value = time;
    renderer.setRenderTarget(null);
    this.quad.render(renderer);
  }

  dispose(): void {
    this.target.dispose();
    this.bloom.dispose();
    this.final.dispose();
    this.quad.dispose();
  }
}
