import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { views } from "../../src/views/data";

const result: unknown = JSON.parse(readFileSync(new URL("../../src/views/fixtures/scorecard.sample.json", import.meta.url), "utf8"));

describe("views.benchResults", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads the scorecard from the API", async () => {
    const fetch = vi.fn(async () => Response.json(result));
    vi.stubGlobal("fetch", fetch);
    await expect(views.benchResults()).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/bench/scorecard", {
      headers: { accept: "application/json" },
      signal: expect.any(AbortSignal),
    });
  });

  it("preserves the API's empty result", async () => {
    vi.stubGlobal("fetch", async () => Response.json(null));
    await expect(views.benchResults()).resolves.toBeNull();
  });

  it("rejects malformed data", async () => {
    vi.stubGlobal("fetch", async () => Response.json({ seeds: [] }));
    await expect(views.benchResults()).rejects.toThrow("invalid bench scorecard");
  });

  it("surfaces an unreadable result from the API", async () => {
    vi.stubGlobal("fetch", async () => Response.json({ detail: "Scorecard file unreadable." }, { status: 503 }));
    await expect(views.benchResults()).rejects.toMatchObject({ status: 503, message: "Scorecard file unreadable." });
  });
});
