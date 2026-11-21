// The resolution cap and the adaptive ladder of the scene (report section 2.4).
import { describe, expect, it } from "vitest";
import { ADAPT, AdaptiveQuality, LADDER, pixelRatio, qualityMode, TIERS } from "../../../src/fx/scene/quality";

/** Feeds `seconds` of frames at `fps` and counts the rung changes. */
function run(q: AdaptiveQuality, fps: number, seconds: number): number {
  let changes = 0;
  const dt = 1 / fps;
  for (let t = 0; t < seconds; t += dt) if (q.sample(dt)) changes += 1;
  return changes;
}

describe("pixelRatio", () => {
  it("caps the device pixel ratio at 1.5", () => {
    expect(pixelRatio(800, 600, 2, TIERS.high.maxPixels)).toBe(1.5);
    expect(pixelRatio(800, 600, 1, TIERS.high.maxPixels)).toBe(1);
  });

  it("never exceeds the tier's pixel budget", () => {
    for (const tier of Object.values(TIERS)) {
      for (const [w, h] of [
        [1920, 1080],
        [2560, 1440],
        [1536, 735],
      ]) {
        const pr = pixelRatio(w, h, 2, tier.maxPixels);
        expect(w * h * pr * pr).toBeLessThanOrEqual(tier.maxPixels * 1.0001);
      }
    }
    // 2560 x 1440 device pixels is exactly the high budget at 1x
    expect(pixelRatio(2560, 1440, 1, TIERS.high.maxPixels)).toBeCloseTo(1, 1);
  });

  it("scales by the adaptive multiplier after the cap", () => {
    expect(pixelRatio(1920, 1080, 2, TIERS.high.maxPixels, 0.7)).toBeCloseTo(0.7 * Math.sqrt(3_700_000 / (1920 * 1080)));
  });
});

describe("qualityMode", () => {
  it("reads fxq and falls back to auto", () => {
    expect(qualityMode("?fx=1&fxq=low")).toBe("low");
    expect(qualityMode("?fxq=MID")).toBe("mid");
    expect(qualityMode("?fxq=ultra")).toBe("auto");
    expect(qualityMode("")).toBe("auto");
  });
});

describe("AdaptiveQuality", () => {
  it("stays on the top rung at 60 fps", () => {
    const q = new AdaptiveQuality();
    expect(run(q, 60, 30)).toBe(0);
    expect(q.current.name).toBe("high");
    expect(q.fps).toBeGreaterThan(59);
  });

  it("waits for the warm-up and a full window before it judges", () => {
    const q = new AdaptiveQuality();
    expect(run(q, 30, ADAPT.warmup + ADAPT.window - 0.2)).toBe(0);
    expect(run(q, 30, 0.4)).toBe(1);
  });

  it("drops bloom first, then resolution down to 0.7", () => {
    const q = new AdaptiveQuality();
    run(q, 40, 2 + 3 * 10);
    expect(q.current).toEqual(LADDER[LADDER.length - 1]);
    expect(q.current.multiplier).toBe(0.7);
    expect(LADDER[1]).toMatchObject({ bloom: false, multiplier: 1 });
  });

  it("climbs back only after 10 s of smooth frames", () => {
    const q = new AdaptiveQuality();
    run(q, 40, 2 + 3.1);
    expect(q.rung).toBe(1);
    expect(run(q, 60, 8.5)).toBe(0);
    expect(run(q, 60, 3.5)).toBe(1);
    expect(q.rung).toBe(0);
  });

  it("ignores pauses such as a hidden tab", () => {
    const q = new AdaptiveQuality();
    run(q, 60, 4);
    expect(q.sample(5)).toBe(false);
    expect(run(q, 60, 10)).toBe(0);
  });

  it("freezes after four changes of direction", () => {
    const q = new AdaptiveQuality();
    run(q, 60, 2);
    for (let i = 0; i < 6; i++) {
      run(q, 30, 6.5); // at least one window entirely slow: a step down
      run(q, 60, 16); // ten smooth seconds after the mixed window: a step up
    }
    expect(q.frozen).toBe(true);
    const rung = q.rung;
    run(q, 20, 30);
    expect(q.rung).toBe(rung);
  });
});
