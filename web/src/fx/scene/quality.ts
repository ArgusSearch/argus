// Resolution cap and adaptive quality (report section 2.4). Pure: the scene feeds it frame times and reads
// back what to render at.

export type Tier = "low" | "mid" | "high";
export type QualityMode = "auto" | Tier;

export interface TierSpec {
  /** most drawing-buffer pixels */
  maxPixels: number;
  bloom: boolean;
  /** far and near snow flakes */
  snow: [number, number];
  /** points that travel along the edges */
  flow: number;
  /** color fringe during fast camera moves */
  fringe: boolean;
  /** MSAA samples of the scene buffer */
  samples: number;
}

export const TIERS: Readonly<Record<Tier, TierSpec>> = {
  high: { maxPixels: 3_700_000, bloom: true, snow: [1200, 200], flow: 600, fringe: true, samples: 4 },
  mid: { maxPixels: 2_100_000, bloom: true, snow: [800, 120], flow: 400, fringe: true, samples: 4 },
  low: { maxPixels: 1_200_000, bloom: false, snow: [480, 80], flow: 240, fringe: false, samples: 2 },
};

/** The picture is allowed to be a little soft: fog and bloom hide it, the frame budget does not. */
export const MAX_DEVICE_PIXEL_RATIO = 1.5;

/** Reads `fxq` from a query string: a fixed tier, or "auto" (the default). */
export function qualityMode(search: string): QualityMode {
  const q = new URLSearchParams(search).get("fxq")?.trim().toLowerCase();
  return q === "low" || q === "mid" || q === "high" ? q : "auto";
}

/**
 * Pixel ratio of the drawing buffer for a canvas of `width` x `height` CSS pixels: the device pixel ratio capped
 * at 1.5 and at the tier's pixel budget, then scaled by the adaptive multiplier.
 */
export function pixelRatio(width: number, height: number, devicePixelRatio: number, maxPixels: number, multiplier = 1): number {
  const area = Math.max(1, width * height);
  const capped = Math.min(Math.max(devicePixelRatio, 0.5), MAX_DEVICE_PIXEL_RATIO, Math.sqrt(maxPixels / area));
  return capped * multiplier;
}

/** One rung of the automatic ladder: bloom is the first thing to go, then resolution in steps of 0.1 down to 0.7. */
export interface Rung {
  name: string;
  bloom: boolean;
  multiplier: number;
}

export const LADDER: readonly Rung[] = [
  { name: "high", bloom: true, multiplier: 1 },
  { name: "no-bloom", bloom: false, multiplier: 1 },
  { name: "0.9x", bloom: false, multiplier: 0.9 },
  { name: "0.8x", bloom: false, multiplier: 0.8 },
  { name: "0.7x", bloom: false, multiplier: 0.7 },
];

export const ADAPT = {
  /** seconds after the first frame before any judgement */
  warmup: 2,
  /** seconds per measuring window */
  window: 3,
  /** frames a window needs to count */
  minFrames: 5,
  /** below this average a window steps down */
  low: 55,
  /** at or above this for `recover` seconds steps back up */
  high: 59,
  recover: 10,
  /** a frame longer than this is a pause (hidden tab, debugger), not a slow frame */
  pause: 0.5,
  /** after this many changes of direction the ladder stops moving */
  maxTurns: 4,
};

/**
 * Walks the ladder from frame times. `sample(dt)` returns true when the rung changed. Only used in auto mode;
 * fixed tiers never adapt.
 */
export class AdaptiveQuality {
  rung = 0;
  fps = 0;
  frozen = false;
  private age = 0;
  private windowTime = 0;
  private windowFrames = 0;
  private goodTime = 0;
  private lastDirection = 0;
  private turns = 0;

  get current(): Rung {
    return LADDER[this.rung];
  }

  /** The tab was hidden or the scene paused: forget the half-measured window. */
  reset(): void {
    this.windowTime = 0;
    this.windowFrames = 0;
  }

  sample(dt: number): boolean {
    if (!(dt > 0) || dt > ADAPT.pause) {
      this.reset();
      return false;
    }
    this.age += dt;
    if (this.age < ADAPT.warmup) return false;
    this.windowTime += dt;
    this.windowFrames += 1;
    if (this.windowTime < ADAPT.window || this.windowFrames < ADAPT.minFrames) return false;

    const fps = this.windowFrames / this.windowTime;
    const span = this.windowTime;
    this.fps = fps;
    this.reset();
    if (this.frozen) return false;

    if (fps < ADAPT.low) {
      this.goodTime = 0;
      if (this.rung < LADDER.length - 1) return this.move(1);
      return false;
    }
    if (fps >= ADAPT.high) {
      this.goodTime += span;
      if (this.goodTime >= ADAPT.recover && this.rung > 0) {
        this.goodTime = 0;
        return this.move(-1);
      }
    } else {
      this.goodTime = 0;
    }
    return false;
  }

  private move(direction: 1 | -1): boolean {
    if (this.lastDirection !== 0 && direction !== this.lastDirection) this.turns += 1;
    this.lastDirection = direction;
    this.rung += direction;
    if (this.turns >= ADAPT.maxTurns) this.frozen = true;
    return true;
  }
}
