import { beforeEach, describe, expect, it, vi } from "vitest";
import { ago, loadThreads, modelLabel, revealed, revealStep, revealTokens, saveThreads, threadTitle, upsertThread, workedFor, type ChatThread } from "./chat";
import type { AgentHealth } from "../lib/agent";

const thread = (id: string, updatedAt: number, turns = 1): ChatThread => ({
  id,
  title: `Thread ${id}`,
  incident: null,
  conversation: null,
  turns: Array.from({ length: turns }, (_, i) => ({ id: i, question: "Why?", answer: null, error: null, stopped: false, after: 0, askedAt: 0, answeredAt: null })),
  updatedAt,
});

describe("the streamed reveal", () => {
  it("never cuts a receipt tag and every prefix is valid text", () => {
    const text = "Revenue fell 12% [q1].\n- Traffic held [q2]";
    const tokens = revealTokens(text);
    expect(tokens.join("")).toBe(text);
    expect(tokens).toContain(" [q1].");
    for (let i = 0; i <= tokens.length; i++) expect(text.startsWith(revealed(tokens, i))).toBe(true);
  });

  it("streams short answers word by word and long ones in about a hundred frames", () => {
    expect(revealStep(40)).toBe(1);
    expect(Math.ceil(960 / revealStep(960))).toBeLessThanOrEqual(96);
  });
});

describe("saved threads", () => {
  beforeEach(() => {
    const data = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => data.get(k) ?? null,
      setItem: (k: string, v: string) => void data.set(k, v),
      clear: () => data.clear(),
    });
  });

  it("keeps threads newest first, drops empty ones and caps the list", () => {
    let list: ChatThread[] = [];
    for (let i = 0; i < 25; i++) list = upsertThread(list, thread(`t${i}`, i));
    expect(list).toHaveLength(20);
    expect(list[0].id).toBe("t24");
    expect(upsertThread(list, thread("t24", 99, 0)).some((t) => t.id === "t24")).toBe(false);
  });

  it("round-trips through storage and marks an answer that never came as stopped", () => {
    saveThreads("live", [thread("a", 1), thread("b", 2)]);
    const back = loadThreads("live");
    expect(back.map((t) => t.id)).toEqual(["b", "a"]);
    expect(back[0].turns[0].stopped).toBe(true);
    expect(loadThreads("demo:x")).toEqual([]);
  });

  it("reads a broken value as no threads", () => {
    localStorage.setItem("argus.chat.threads.v1:live", "{not json");
    expect(loadThreads("live")).toEqual([]);
  });
});

describe("labels", () => {
  it("names a thread by its first question, cut at a word", () => {
    expect(threadTitle("  Why did   revenue drop? ")).toBe("Why did revenue drop?");
    const long = threadTitle("Could the higher traffic from the newsletter campaign explain the extra ad spend this week?");
    expect(long.endsWith("…")).toBe(true);
    expect(long.length).toBeLessThanOrEqual(61);
  });

  it("says how long a turn worked and how long ago a thread was used", () => {
    expect(workedFor(4200)).toBe("4.2s");
    expect(workedFor(42_000)).toBe("42s");
    expect(workedFor(72_000)).toBe("1m 12s");
    expect(ago(0, 30_000)).toBe("now");
    expect(ago(0, 5 * 60_000)).toBe("5m");
    expect(ago(0, 3 * 3600_000)).toBe("3h");
  });

  it("shows the agent's model, else its mode, else that it is offline", () => {
    const base = { enabled: true, mode: "live", caps: {}, usd: 0 } as const;
    expect(modelLabel(null)).toBe("Agent offline");
    expect(modelLabel({ ...base, models: { ask: "anthropic/claude-sonnet-5-5" } } as AgentHealth)).toBe("claude-sonnet-5-5");
    expect(modelLabel({ ...base, models: [] } as AgentHealth)).toBe("Live agent");
    expect(modelLabel({ ...base, mode: "replay", models: {} } as AgentHealth)).toBe("Recorded agent");
  });
});
