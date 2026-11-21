// The camera rig (A12): a telephoto camera that frames a set of blocks inside the safe rectangle (the graph
// panel) while the canvas covers the whole window, glides with critically damped springs so it can be
// retargeted mid-move, drifts in a slow idle orbit and leans a little toward the pointer.

import { PerspectiveCamera, Vector3 } from "three";

export const FOV = 28;
/** look-down angle and slight turn of the resting camera, radians */
export const PITCH = 0.92;
export const YAW = -0.07;
/** In a tall rectangle the camera turns a quarter so the graph runs top to bottom and fills the height. */
export const PORTRAIT_YAW = Math.PI / 2 - 0.07;
export const PORTRAIT_PITCH = 1.02;
/** below this width-to-height ratio the safe rectangle counts as tall */
export const PORTRAIT_BELOW = 0.95;

/** The canvas and, inside it, the rectangle the graph is framed in (CSS pixels, canvas coordinates). */
export interface SafeRect {
  canvasWidth: number;
  canvasHeight: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Framing {
  center: Vector3;
  distance: number;
}

const UP = new Vector3(0, 1, 0);

/** Unit vector from the target toward the camera for a yaw and pitch. */
export function backVector(yaw: number, pitch: number, out = new Vector3()): Vector3 {
  return out.set(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch));
}

/**
 * Pure framing: the target point and distance at which every point of `points` (flat xyz triples) fits a view of
 * vertical field of view `fov` (degrees) and `aspect`, with `pad` (0 to 1) of the frame kept free on each side.
 */
export function frame(points: ArrayLike<number>, yaw: number, pitch: number, fov: number, aspect: number, pad: number, out: Framing): Framing {
  const back = backVector(yaw, pitch, new Vector3());
  const right = new Vector3().crossVectors(UP, back).normalize();
  const up = new Vector3().crossVectors(back, right);
  const tanV = Math.tan(((fov / 2) * Math.PI) / 180) * (1 - pad);
  const tanH = tanV * aspect;
  const n = Math.floor(points.length / 3);
  if (n === 0) {
    out.center.set(0, 0, 0);
    out.distance = 30;
    return out;
  }
  // center in the view plane
  let cx = 0;
  let cy = 0;
  let cz = 0;
  for (let i = 0; i < n; i++) {
    cx += points[i * 3];
    cy += points[i * 3 + 1];
    cz += points[i * 3 + 2];
  }
  const c = new Vector3(cx / n, cy / n, cz / n);
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  const p = new Vector3();
  for (let i = 0; i < n; i++) {
    p.set(points[i * 3], points[i * 3 + 1], points[i * 3 + 2]).sub(c);
    const x = p.dot(right);
    const y = p.dot(up);
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  c.addScaledVector(right, (minX + maxX) / 2).addScaledVector(up, (minY + maxY) / 2);
  // the distance at which every point is inside both half-angles
  let distance = 0;
  for (let i = 0; i < n; i++) {
    p.set(points[i * 3], points[i * 3 + 1], points[i * 3 + 2]).sub(c);
    const x = Math.abs(p.dot(right));
    const y = Math.abs(p.dot(up));
    const z = p.dot(back);
    distance = Math.max(distance, x / tanH + z, y / tanV + z);
  }
  out.center.copy(c);
  out.distance = distance;
  return out;
}

/** Critically damped spring toward `target` (Game Programming Gems 4, 1.10). Returns the new value. */
export function smoothDamp(current: number, target: number, velocity: { v: number }, smoothTime: number, dt: number): number {
  const omega = 2 / Math.max(smoothTime, 1e-4);
  const x = omega * dt;
  const exp = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
  const change = current - target;
  const temp = (velocity.v + omega * change) * dt;
  velocity.v = (velocity.v - omega * temp) * exp;
  return target + (change + temp) * exp;
}

export class CameraRig {
  readonly camera = new PerspectiveCamera(FOV, 1, 0.5, 400);
  readonly center = new Vector3(0, 0, 0);
  distance = 40;
  /** relative speed of the last update: (distance moved / distance), per second */
  speed = 0;
  private readonly goal: Framing = { center: new Vector3(), distance: 40 };
  private readonly vel = { x: { v: 0 }, y: { v: 0 }, z: { v: 0 }, d: { v: 0 }, yaw: { v: 0 }, pitch: { v: 0 } };
  private yawGoal = YAW;
  private pitchGoal = PITCH;
  private yaw = YAW;
  private pitch = PITCH;
  private rect: SafeRect = { canvasWidth: 1, canvasHeight: 1, x: 0, y: 0, width: 1, height: 1 };
  private parallaxX = 0;
  private parallaxY = 0;
  private time = 0;
  private readonly back = new Vector3();
  private readonly prev = new Vector3();
  private placed = false;
  /** extra distance and look-down during the intro, 1 at its start and 0 when settled */
  intro = 0;

  get aspect(): number {
    return this.rect.width / Math.max(1, this.rect.height);
  }

  setRect(rect: SafeRect): void {
    this.rect = rect;
    const cam = this.camera;
    cam.aspect = this.aspect;
    const portrait = this.aspect < PORTRAIT_BELOW;
    this.yawGoal = portrait ? PORTRAIT_YAW : YAW;
    this.pitchGoal = portrait ? PORTRAIT_PITCH : PITCH;
    const inside = rect.x === 0 && rect.y === 0 && rect.width === rect.canvasWidth && rect.height === rect.canvasHeight;
    if (inside) cam.clearViewOffset();
    else cam.setViewOffset(rect.width, rect.height, -rect.x, -rect.y, rect.canvasWidth, rect.canvasHeight);
    cam.updateProjectionMatrix();
  }

  /** Frames `points` (flat xyz) with `pad` of the safe rectangle kept free; `minDistance` keeps it from diving in. */
  target(points: ArrayLike<number>, pad: number, minDistance: number): void {
    frame(points, this.yawGoal, this.pitchGoal, FOV, this.aspect, pad, this.goal);
    this.goal.distance = Math.max(this.goal.distance, minDistance);
    if (!this.placed) this.snap();
  }

  /** Jumps to the goal (first frame, reduced motion). */
  snap(): void {
    this.center.copy(this.goal.center);
    this.distance = this.goal.distance;
    this.yaw = this.yawGoal;
    this.pitch = this.pitchGoal;
    this.vel.x.v = this.vel.y.v = this.vel.z.v = this.vel.d.v = this.vel.yaw.v = this.vel.pitch.v = 0;
    this.placed = true;
  }

  /**
   * Moves the camera. `pointer` is in -1..1 over the window (null when outside); `still` turns off the glide,
   * the idle orbit and the parallax (reduced motion).
   */
  update(dt: number, pointer: { x: number; y: number } | null, still: boolean): void {
    this.time += dt;
    this.prev.copy(this.center);
    const before = this.distance;
    if (still) this.snap();
    else {
      const t = 0.62;
      this.center.x = smoothDamp(this.center.x, this.goal.center.x, this.vel.x, t, dt);
      this.center.y = smoothDamp(this.center.y, this.goal.center.y, this.vel.y, t, dt);
      this.center.z = smoothDamp(this.center.z, this.goal.center.z, this.vel.z, t, dt);
      this.distance = smoothDamp(this.distance, this.goal.distance, this.vel.d, 0.78, dt);
      this.yaw = smoothDamp(this.yaw, this.yawGoal, this.vel.yaw, 0.7, dt);
      this.pitch = smoothDamp(this.pitch, this.pitchGoal, this.vel.pitch, 0.7, dt);
    }
    const moved = this.prev.distanceTo(this.center) + Math.abs(this.distance - before);
    this.speed = dt > 0 ? moved / dt / Math.max(this.distance, 1) : 0;

    const follow = 1 - Math.pow(1 - 0.035, dt * 60);
    const px = still || !pointer ? 0 : pointer.x;
    const py = still || !pointer ? 0 : pointer.y;
    this.parallaxX += (px - this.parallaxX) * follow;
    this.parallaxY += (py - this.parallaxY) * follow;
    const orbit = still ? 0 : 0.035 * Math.sin((this.time * Math.PI * 2) / 14);
    const ease = this.intro * this.intro * (3 - 2 * this.intro);
    const yaw = this.yaw + orbit + this.parallaxX * 0.025 - ease * 0.16;
    const pitch = this.pitch - this.parallaxY * 0.014 + ease * 0.12;
    const distance = this.distance * (1 + ease * 0.45);
    backVector(yaw, pitch, this.back);
    this.camera.position.copy(this.center).addScaledVector(this.back, distance);
    this.camera.lookAt(this.center);
    this.camera.updateMatrixWorld();
  }
}
