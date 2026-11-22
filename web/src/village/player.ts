// The village clock: plays a timeline at a speed, halts at an approval gate until you decide, and tells its
// subscribers when anything they render changes. Time is in timeline seconds (speed 1).

import type { Timeline } from "./timeline";
import { slotAt, TRAVEL } from "./timeline";

export const SPEEDS = [0.5, 1, 2, 4] as const;

type Listener = () => void;

export class Player {
  time = 0;
  speed = 1;
  playing = true;
  private tl: Timeline = { slots: [], total: 0, waiting: false };
  private last = 0;
  private frame = 0;
  private readonly listeners = new Set<Listener>();
  private signature = "";
  /** live sources append beats: when the clock falls far behind, it plays faster to catch up */
  follow = false;

  get timeline(): Timeline {
    return this.tl;
  }

  /** Swaps the timeline (a decision, new live beats, another tape). The clock keeps its time unless `restart`. */
  load(tl: Timeline, restart = false): void {
    this.tl = tl;
    if (restart) this.time = 0;
    this.time = Math.min(this.time, tl.total);
    this.emit(true);
  }

  start(): void {
    if (this.frame || typeof requestAnimationFrame === "undefined") return;
    this.last = performance.now();
    const loop = (now: number) => {
      this.frame = requestAnimationFrame(loop);
      const dt = Math.min(0.25, Math.max(0, (now - this.last) / 1000));
      this.last = now;
      this.advance(dt);
    };
    this.frame = requestAnimationFrame(loop);
  }

  stop(): void {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  /** Advances the clock by `dt` wall seconds. Exposed for tests and for headless capture. */
  advance(dt: number): void {
    if (!this.playing || !this.tl.slots.length) return this.emit(false);
    let rate = this.speed;
    if (this.follow) {
      const behind = this.tl.total - this.time;
      if (behind > 30) rate *= Math.min(8, behind / 15);
    }
    this.time = Math.min(this.tl.total, this.time + dt * rate);
    this.emit(false);
  }

  setPlaying(on: boolean): void {
    this.playing = on;
    this.emit(true);
  }

  setSpeed(speed: number): void {
    this.speed = speed;
    this.emit(true);
  }

  seek(time: number): void {
    this.time = Math.max(0, Math.min(this.tl.total, time));
    this.emit(true);
  }

  /** Skips to the start of the next beat. */
  next(): void {
    const i = slotAt(this.tl, this.time);
    const slot = this.tl.slots[i + 1];
    this.seek(slot ? slot.start : this.tl.total);
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** What the React side renders from: changes only when a beat starts, a flight lands, or the controls move. */
  private emit(force: boolean): void {
    const i = slotAt(this.tl, this.time);
    const slot = this.tl.slots[i];
    const landed = slot ? (slot.from ? this.time - slot.start >= TRAVEL : true) : true;
    const late = slot ? this.time >= slot.start + slot.length * 0.6 : false;
    const sig = `${i}|${landed}|${late}|${this.time >= this.tl.total}|${this.playing}|${this.speed}|${this.tl.slots.length}`;
    if (!force && sig === this.signature) return;
    this.signature = sig;
    for (const l of [...this.listeners]) l();
  }
}
