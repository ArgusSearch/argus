// Timing helpers of the style layer: cascades, CSS time tokens and the step timeline of the opening.
import { describe, expect, it } from "vitest";
import { cssTimeMs, stagger, timeline, type Clock } from "../../src/fx/motion";

/** A clock that only moves when told to. */
function manualClock() {
  let now = 0;
  let next = 0;
  const pending = new Map<number, { at: number; run: () => void }>();
  const clock: Clock = {
    set(run, ms) {
      next += 1;
      pending.set(next, { at: now + ms, run });
      return next;
    },
    clear(handle) {
      pending.delete(handle as number);
    },
  };
  const advance = (ms: number) => {
    now += ms;
    const due = [...pending.entries()].filter(([, t]) => t.at <= now).sort((a, b) => a[1].at - b[1].at);
    for (const [id, t] of due) {
      pending.delete(id);
      t.run();
    }
  };
  return { clock, advance, pending };
}

describe("stagger", () => {
  it("spaces items by the step", () => {
    expect([0, 1, 2, 3].map((i) => stagger(i, 40))).toEqual([0, 40, 80, 120]);
  });

  it("caps long lists so the last items do not wait forever", () => {
    expect(stagger(50, 40)).toBe(12 * 40);
    expect(stagger(50, 40, 6)).toBe(240);
  });

  it("never returns a negative delay", () => {
    expect(stagger(-3, 40)).toBe(0);
    expect(stagger(2, -10)).toBe(0);
  });
});

describe("cssTimeMs", () => {
  it("reads ms and s", () => {
    expect(cssTimeMs("400ms", 0)).toBe(400);
    expect(cssTimeMs("1.25s", 0)).toBe(1250);
    expect(cssTimeMs(" 3000ms ", 0)).toBe(3000);
    expect(cssTimeMs(".5s", 0)).toBe(500);
  });

  it("turns reduced motion's 1ms into 1", () => {
    expect(cssTimeMs("1ms", 3000)).toBe(1);
  });

  it("falls back when the token is missing or not a time", () => {
    expect(cssTimeMs("", 750)).toBe(750);
    expect(cssTimeMs(null, 750)).toBe(750);
    expect(cssTimeMs("fast", 750)).toBe(750);
    expect(cssTimeMs("-200ms", 750)).toBe(750);
  });
});

describe("timeline", () => {
  it("runs each step at its offset, in order", () => {
    const { clock, advance } = manualClock();
    const ran: string[] = [];
    timeline(
      [
        [750, () => ran.push("loader gone")],
        [0, () => ran.push("intro")],
        [1950, () => ran.push("ready")],
      ],
      clock,
    );
    advance(0);
    expect(ran).toEqual(["intro"]);
    advance(750);
    expect(ran).toEqual(["intro", "loader gone"]);
    advance(1200);
    expect(ran).toEqual(["intro", "loader gone", "ready"]);
  });

  it("cancels the steps not yet run", () => {
    const { clock, advance, pending } = manualClock();
    const ran: string[] = [];
    const cancel = timeline(
      [
        [100, () => ran.push("a")],
        [200, () => ran.push("b")],
      ],
      clock,
    );
    advance(100);
    cancel();
    advance(500);
    expect(ran).toEqual(["a"]);
    expect(pending.size).toBe(0);
  });
});
