import { afterEach, describe, expect, it, vi } from "vitest";

const metric = { name: "cost_per_impression", description: "Ad spend per impression", sql: "select 1" };

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("public graph placement", () => {
  it("keeps the session cookie on placement and graph requests and reopens an expired session", async () => {
    vi.stubEnv("VITE_ARGUS_PUBLIC_API", "1");
    vi.stubEnv("VITE_ARGUS_API_URL", "https://api.example");
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json({ csrf_token: "first" }))
      .mockResolvedValueOnce(Response.json({ placed_as: "EXACT" }))
      .mockResolvedValueOnce(Response.json({ placements: [] }))
      .mockResolvedValueOnce(Response.json({ nodes: [] }))
      .mockResolvedValueOnce(Response.json({ id: "gx-1" }))
      .mockResolvedValueOnce(Response.json({ detail: "Expired session" }, { status: 403 }))
      .mockResolvedValueOnce(Response.json({ csrf_token: "renewed" }))
      .mockResolvedValueOnce(Response.json({ placed_as: "EXACT" }));
    vi.stubGlobal("fetch", fetch);
    const { extensionApi } = await import("./api");
    const { api } = await import("../lib/api");

    await expect(extensionApi.place(metric)).resolves.toEqual({ placed_as: "EXACT" });
    await extensionApi.state();
    await api.graph();
    await api.receipt("gx-1");
    await expect(extensionApi.place(metric)).resolves.toEqual({ placed_as: "EXACT" });

    expect(fetch.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([
      "/agent/operator/session", "/graph/metrics", "/graph/metrics", "/graph", "/receipts/gx-1",
      "/graph/metrics", "/agent/operator/session", "/graph/metrics",
    ]);
    expect(fetch.mock.calls.every(([, init]) => init.credentials === "include")).toBe(true);
    expect(fetch.mock.calls[1][1].headers["X-Argus-CSRF"]).toBe("first");
    expect(fetch.mock.calls[5][1].headers["X-Argus-CSRF"]).toBe("first");
    expect(fetch.mock.calls[7][1].headers["X-Argus-CSRF"]).toBe("renewed");
  });

  it("posts directly to the local API", async () => {
    vi.stubEnv("VITE_ARGUS_PUBLIC_API", "0");
    vi.stubEnv("VITE_ARGUS_API_URL", "");
    const fetch = vi.fn().mockResolvedValue(Response.json({ placed_as: "EXACT" }));
    vi.stubGlobal("fetch", fetch);
    const { extensionApi } = await import("./api");

    await extensionApi.place(metric);
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/graph/metrics", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(metric),
    });
  });
});
