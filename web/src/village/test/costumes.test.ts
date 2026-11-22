import { describe, expect, it } from "vitest";
import { calendarLooks, DEFAULT_LOOK, defaultLook, LOOKS } from "../avatars/costumes";
import { ROLE_IDS } from "../roles";

describe("role costumes", () => {
  it("gives every role two looks, numbered 1 and 2, with distinct names", () => {
    for (const role of ROLE_IDS) {
      const looks = LOOKS[role];
      expect(looks.map((l) => l.id)).toEqual([1, 2]);
      expect(new Set(looks.map((l) => l.name)).size).toBe(2);
      for (const look of looks) {
        expect(look.reads.length).toBeGreaterThan(0);
        expect(typeof look.draw).toBe("function");
      }
    }
    expect(calendarLooks.map((l) => l.id)).toEqual([1, 2]);
  });

  it("dresses every avatar in look 1 by default", () => {
    expect(DEFAULT_LOOK).toBe(1);
    for (const role of ROLE_IDS) expect(defaultLook(role)).toBe(LOOKS[role][0]);
  });
});
