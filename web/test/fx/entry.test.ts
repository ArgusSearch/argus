// The entry screen (demo sign-in): shown once per tab on a plain load, never in front of a deep link.
import { describe, expect, it } from "vitest";
import { entryWanted, searchAfterEntry } from "../../src/fx/entry/gate";

describe("entryWanted", () => {
  it("shows on a plain load until the tab entered once", () => {
    expect(entryWanted("?fx=1", false)).toBe(true);
    expect(entryWanted("", false)).toBe(true);
    expect(entryWanted("?fx=1", true)).toBe(false);
  });

  it("never stands in front of the recording URL or another deep link", () => {
    expect(entryWanted("?demo=1&captions=1&fx=1", false)).toBe(false);
    expect(entryWanted("?fx=1&view=incident&incident=INC-0001", false)).toBe(false);
    expect(entryWanted("?fx=1&fxintro=0&view=graph", false)).toBe(false);
    expect(entryWanted("?fx=1&agentdemo=s4", false)).toBe(false);
    expect(entryWanted("?fx=1&agentrun=abc", false)).toBe(false);
  });

  it("follows the entry override either way", () => {
    expect(entryWanted("?fx=1&entry=1", true)).toBe(true);
    expect(entryWanted("?fx=1&demo=1&entry=1", false)).toBe(true);
    expect(entryWanted("?fx=1&entry=0", false)).toBe(false);
    expect(entryWanted("?fx=1&entry=maybe", false)).toBe(true);
  });
});

describe("searchAfterEntry", () => {
  it("drops only the override", () => {
    expect(searchAfterEntry("?fx=1&entry=1")).toBe("?fx=1");
    expect(searchAfterEntry("?entry=1")).toBe("");
    expect(searchAfterEntry("?fx=night&fxq=high")).toBe("?fx=night&fxq=high");
  });
});
