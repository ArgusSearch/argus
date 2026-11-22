import { afterEach, describe, expect, it, vi } from "vitest";

const first = { revision: 1, simulator: false, settings: { autonomy: { monitor: "alone" }, ai: { api_key_configured: false } } };
const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("settings operator requests", () => {
  it("uses one credentialed operator session for the read, save and undo", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(reply({ csrf_token: "operator-token" }))
      .mockResolvedValueOnce(reply(first))
      .mockResolvedValueOnce(reply({ ...first, revision: 2, settings: { autonomy: { monitor: "off" } } }))
      .mockResolvedValueOnce(reply({ ...first, revision: 3 }));
    vi.stubGlobal("fetch", fetch);
    const { loadSettings, saveSettings, undoSettings } = await import("../../src/settings/operator");

    await loadSettings();
    const saved = await saveSettings("autonomy", 1, { monitor: "off" });
    const undone = await undoSettings("autonomy", saved.revision);

    expect(undone.settings.autonomy.monitor).toBe("alone");
    expect(fetch.mock.calls.map(([path]) => path)).toEqual([
      "/settings/operator/session", "/settings", "/settings/autonomy", "/settings/autonomy/undo",
    ]);
    const [, request] = fetch.mock.calls[2]!;
    expect(request).toMatchObject({ method: "PATCH", credentials: "include", headers: { "X-Argus-CSRF": "operator-token" } });
    expect(JSON.parse(request.body)).toEqual({ revision: 1, changes: { monitor: "off" } });
  });

  it("renews an expired session while keeping secret fields out of the settings snapshot", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(reply({ csrf_token: "expired" }))
      .mockResolvedValueOnce(reply({ detail: "an operator session and its CSRF token are required" }, 403))
      .mockResolvedValueOnce(reply({ csrf_token: "fresh" }))
      .mockResolvedValueOnce(reply({ ...first, settings: { ai: { api_key_configured: true } } }));
    vi.stubGlobal("fetch", fetch);
    const { saveSettings } = await import("../../src/settings/operator");
    const saved = await saveSettings("ai", 1, { provider: "anthropic", api_key: "test-key-sample" });

    expect(saved.settings.ai).toEqual({ api_key_configured: true });
    expect(fetch.mock.calls[3]?.[1].headers["X-Argus-CSRF"]).toBe("fresh");
  });
});
