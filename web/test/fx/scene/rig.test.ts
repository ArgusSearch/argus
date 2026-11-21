// The camera frames a set of blocks inside the safe rectangle, with perspective taken into account.
import { PerspectiveCamera, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { backVector, FOV, frame, PITCH, PORTRAIT_PITCH, PORTRAIT_YAW, smoothDamp, YAW } from "../../../src/fx/scene/rig";
import { BLOCK, layout } from "../../../src/fx/scene/layout";
import { loadGraph } from "./fixtures";

function corners(): number[] {
  const out: number[] = [];
  for (const p of layout(loadGraph()).values()) {
    const [hx, hy, hz] = [(BLOCK[0] * p.scale[0]) / 2, (BLOCK[1] * p.scale[1]) / 2, (BLOCK[2] * p.scale[2]) / 2];
    for (let k = 0; k < 8; k++) out.push(p.position[0] + (k & 1 ? hx : -hx), p.position[1] + (k & 2 ? hy : -hy), p.position[2] + (k & 4 ? hz : -hz));
  }
  return out;
}

function bounds(points: number[], yaw: number, pitch: number, aspect: number, center: Vector3, distance: number) {
  const cam = new PerspectiveCamera(FOV, aspect, 0.1, 1000);
  cam.position.copy(center).addScaledVector(backVector(yaw, pitch), distance);
  cam.lookAt(center);
  cam.updateMatrixWorld();
  let [x0, x1, y0, y1] = [Infinity, -Infinity, Infinity, -Infinity];
  const v = new Vector3();
  for (let i = 0; i < points.length; i += 3) {
    v.set(points[i], points[i + 1], points[i + 2]).project(cam);
    [x0, x1, y0, y1] = [Math.min(x0, v.x), Math.max(x1, v.x), Math.min(y0, v.y), Math.max(y1, v.y)];
  }
  return { x0, x1, y0, y1 };
}

describe("frame", () => {
  const points = corners();

  it.each([
    ["wide panel", 2.48, YAW, PITCH],
    ["video window", 16 / 9, YAW, PITCH],
    ["tall window", 0.59, PORTRAIT_YAW, PORTRAIT_PITCH],
  ])("fills the %s up to the padding and centers the graph", (_, aspect, yaw, pitch) => {
    const pad = 0.05;
    const out = frame(points, yaw, pitch, FOV, aspect, pad, { center: new Vector3(), distance: 0 });
    const b = bounds(points, yaw, pitch, aspect, out.center, out.distance);
    for (const edge of [b.x0, b.y0]) expect(edge).toBeGreaterThanOrEqual(-1 + pad - 0.01);
    for (const edge of [b.x1, b.y1]) expect(edge).toBeLessThanOrEqual(1 - pad + 0.01);
    const tight = Math.max(b.x1 - b.x0, b.y1 - b.y0);
    expect(tight).toBeCloseTo(2 * (1 - pad), 2);
    expect((b.x0 + b.x1) / 2).toBeCloseTo(0, 2);
    expect((b.y0 + b.y1) / 2).toBeCloseTo(0, 2);
  });
});

describe("smoothDamp", () => {
  it("settles on the target without overshoot", () => {
    const vel = { v: 0 };
    let x = 0;
    let max = 0;
    for (let i = 0; i < 240; i++) {
      x = smoothDamp(x, 10, vel, 0.62, 1 / 60);
      max = Math.max(max, x);
    }
    expect(x).toBeCloseTo(10, 2);
    expect(max).toBeLessThanOrEqual(10.0001);
  });
});
