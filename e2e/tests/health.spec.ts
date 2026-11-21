import { expect, test } from "@playwright/test";
import { LIVE, health } from "./helpers";

test("GET /health answers ok in the expected mode", async ({ request }) => {
  const h = await health(request);
  expect(h.status).toBe("ok");
  expect(h.mode).toBe(LIVE ? "live" : "replay");
});

test("every route marked stub answers 501", async ({ request }) => {
  const res = await request.get("/routes");
  expect(res.ok()).toBeTruthy();
  const routes = (await res.json()) as { method: string; path: string; status: string }[];
  const stubs = routes.filter((r) => r.status === "stub");
  expect(stubs.length, "GET /routes lists the not-yet-built routes").toBeGreaterThan(0);
  for (const r of stubs) {
    const path = r.path.replace("{id}", "INC-0001");
    const answer = await request.fetch(path, { method: r.method, data: r.method === "GET" ? undefined : {} });
    expect(answer.status(), `${r.method} ${r.path}`).toBe(501);
  }
  for (const r of routes.filter((x) => x.status === "implemented" && x.method === "GET" && !x.path.includes("{"))) {
    if (r.path === "/events") continue; // SSE never ends
    const answer = await request.get(r.path);
    expect(answer.status(), `${r.method} ${r.path}`).toBeLessThan(400);
  }
});
