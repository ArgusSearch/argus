// Uniforms every material of the scene shares: one object per uniform, referenced by all materials, so one
// write per frame reaches every shader.

import { Color, Vector2 } from "three";

export interface Env {
  uTime: { value: number };
  uFogColor: { value: Color };
  uFogNear: { value: number };
  uFogDensity: { value: number };
  /** drawing-buffer size in device pixels */
  uResolution: { value: Vector2 };
  uPixelRatio: { value: number };
  uHud: { value: Color };
}

export function createEnv(): Env {
  return {
    uTime: { value: 0 },
    uFogColor: { value: new Color("#a2a8b5") },
    uFogNear: { value: 30 },
    uFogDensity: { value: 0.02 },
    uResolution: { value: new Vector2(1, 1) },
    uPixelRatio: { value: 1 },
    uHud: { value: new Color("#ffffff") },
  };
}
