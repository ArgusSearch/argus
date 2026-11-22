import { describe, expect, it } from "vitest";
import { buildBeats } from "../beats";
import { placePin, roleViews } from "../Overlay";
import { Player } from "../player";
import { ROLES } from "../roles";
import { growthAt, idleBubbles, slotAt, timeline, villageAt, type Timeline } from "../timeline";
import type { VillageTape } from "../types";
import metricTape from "../tapes/metric.json";
import s4Tape from "../tapes/s4.json";

const metric = timeline(buildBeats(metricTape as unknown as VillageTape, { decision: null }));

it("clears old bubbles while the new source catches up to the player", () => {
  const player = new Player();
  player.load(metric);
  player.seek(metric.total);
  const previous = villageAt(metric, player.time, idleBubbles(ROLES));
  expect(roleViews(previous, player).some((role) => role.kind)).toBe(true);
  player.load(timeline([]));
  expect(roleViews(previous, player).every((role) => role.kind === null)).toBe(true);
});

function verdicts(tl: Timeline) {
  return tl.slots.filter((s) => s.beat.role === "cartographer" && s.beat.kind === "verdict");
}

describe("growthAt: the new metric grows into the Cartographer's map", () => {
  it("is empty before the first verdict and grows from 30% into it", () => {
    const first = verdicts(metric)[0];
    const start = first.start + first.length * 0.3;
    expect(growthAt(metric, slotAt(metric, start - 0.01), start - 0.01)).toBeNull();
    const g = growthAt(metric, slotAt(metric, start + 0.5), start + 0.5);
    expect(g?.age).toBeCloseTo(0.5, 5);
  });

  it("follows the verdict: placed, held or rejected", () => {
    const kinds = verdicts(metric).map((s) => {
      const t = s.start + s.length * 0.9;
      return [s.beat.outcome, growthAt(metric, slotAt(metric, t), t)?.kind];
    });
    expect(kinds.length).toBeGreaterThan(1);
    for (const [outcome, kind] of kinds) expect(kind).toBe(outcome === "ok" ? "placed" : outcome === "alarm" ? "rejected" : "held");
  });

  it("holds the previous placement until the next one starts growing", () => {
    const [first, second] = verdicts(metric);
    const at = second.start + second.length * 0.3 - 0.01;
    expect(growthAt(metric, slotAt(metric, at), at)).toEqual({ kind: "placed", age: at - (first.start + first.length * 0.3) });
  });

  it("stays empty in a run without placements", () => {
    const s4 = timeline(buildBeats(s4Tape as unknown as VillageTape, { decision: null }));
    expect(growthAt(s4, s4.slots.length - 1, s4.total)).toBeNull();
  });
});

describe("placePin keeps bubbles clear of the title block", () => {
  const pin = (classes: string[]) => {
    const style: Record<string, string> & { setProperty?: (k: string, v: string) => void } = {};
    style.setProperty = (k: string, v: string) => {
      style[k] = v;
    };
    return { el: { classList: { contains: (c: string) => classes.includes(c) }, style } as unknown as HTMLElement, style };
  };
  const at = (style: Record<string, unknown>) => /translate3d\(([\d.]+)px,\s*([\d.]+)px/.exec(String(style.transform))?.slice(1).map(Number);
  const keepout = { right: 520, bottom: 160 };

  it("slides a bubble that would run into the title sideways past it, the plate stays over its igloo", () => {
    const { el, style } = pin(["vl-pin-role", "on"]);
    placePin(el, 500, 180, true, keepout);
    expect(at(style)).toEqual([500, 180]);
    expect(style["--dodge"]).toBe(`${(520 + 12 - (500 - 140)).toFixed(1)}px`);
    // never further than 220 px: a bubble under the title's middle stays near its igloo
    const deep = pin(["vl-pin-role", "on"]);
    placePin(deep.el, 200, 180, true, keepout);
    expect(deep.style["--dodge"]).toBe("220.0px");
  });

  it("leaves bubbles away from the title, and pins without a bubble, where they are", () => {
    const far = pin(["vl-pin-role", "on"]);
    placePin(far.el, 900, 180, true, keepout);
    expect(far.style["--dodge"]).toBe("0.0px");
    const below = pin(["vl-pin-role", "on"]);
    placePin(below.el, 400, 400, true, keepout);
    expect(below.style["--dodge"]).toBe("0.0px");
    const plate = pin(["vl-pin-role"]);
    placePin(plate.el, 400, 300, true, keepout);
    expect(plate.style["--dodge"]).toBe("0.0px");
    expect(at(plate.style)).toEqual([400, 300]);
  });
});
