import { describe, expect, it } from "vitest";
import { buildBeats } from "../beats";
import { roleViews } from "../Overlay";
import { Player } from "../player";
import { ROLES } from "../roles";
import { idleBubbles, timeline, villageAt } from "../timeline";
import type { VillageTape } from "../types";
import s4Tape from "../tapes/s4.json";

const idle = idleBubbles(ROLES);

function at(t: number) {
  const player = new Player();
  player.load(timeline(buildBeats(s4Tape as unknown as VillageTape, { decision: null })), true);
  player.seek(t);
  return { player, state: villageAt(player.timeline, player.time, idle) };
}

describe("roleViews", () => {
  it("shows WORKING with a clock for the role at work and nothing for idle roles", () => {
    const { player, state } = at(30);
    const views = roleViews(state, player);
    const working = views.filter((v) => v.kind === "working");
    expect(working).toHaveLength(1);
    expect(working[0].role).toBe(state.beat?.role);
    expect(working[0].since).toBeLessThanOrEqual(30);
    expect(views.find((v) => v.role === "operator")?.kind).toBeNull();
  });

  it("shows NEEDS YOU only on the Operator at the approval gate", () => {
    const { player, state } = at(10_000);
    const views = roleViews(state, player);
    expect(views.filter((v) => v.kind === "need").map((v) => v.role)).toEqual(["operator"]);
  });

  it("keeps FINISHED for a few seconds after a role's part, then clears it", () => {
    const { player } = at(0);
    const slots = player.timeline.slots;
    const i = slots.findIndex((s, k) => k > 0 && slots[k - 1].beat.role === "skeptic" && s.beat.role !== "skeptic");
    const end = slots[i].start;
    player.seek(end + 1);
    expect(roleViews(villageAt(player.timeline, player.time, idle), player).find((v) => v.role === "skeptic")?.kind).toBe("finished");
    player.seek(end + 8);
    expect(roleViews(villageAt(player.timeline, player.time, idle), player).find((v) => v.role === "skeptic")?.kind).toBeNull();
  });
});
