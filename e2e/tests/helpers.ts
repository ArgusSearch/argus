import { expect, type APIRequestContext, type ConsoleMessage, type Page } from "@playwright/test";

export const LIVE = process.env.ARGUS_E2E_MODE === "live";

/** The classic interface (Argus Ice became the default page in f6197da). */
export const CLASSIC = "/?classic=1";

export interface Health {
  status: string;
  mode: "replay" | "live";
  last_seq: number;
  run: { playing: boolean; finished: boolean; speed: number; position: number; total: number; loop: boolean };
}

export async function health(request: APIRequestContext): Promise<Health> {
  const res = await request.get("/health");
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as Health;
}

export async function replay(request: APIRequestContext, body: { action?: string; speed?: number }): Promise<void> {
  const res = await request.post("/replay", { data: body });
  expect(res.status(), `POST /replay ${JSON.stringify(body)}`).toBeLessThan(300);
}

/** Collect console errors and failed requests (the documented 501 stubs excepted). */
export function watchErrors(page: Page): () => string[] {
  const errors: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  page.on("response", (res) => {
    if (res.status() >= 400 && res.status() !== 501) errors.push(`http ${res.status()}: ${res.request().method()} ${res.url()}`);
  });
  return () => errors;
}

/** Open the page and fail with a clear message when web/dist was not built. */
export async function openMissionControl(page: Page): Promise<void> {
  // Argus Ice is the default interface since f6197da; these specs check the classic Mission Control
  await page.goto(CLASSIC);
  const body = await page.locator("body").innerText();
  expect(body, "web/dist is missing: run `npm --prefix web run build` first").not.toContain("not built yet");
  await expect(page).toHaveTitle("Argus · Mission Control");
}

/** Start the run from the top (replay) at a fast pace and wait for the incident card. */
export async function runToIncident(page: Page, request: APIRequestContext, id = "INC-0001"): Promise<void> {
  if (!LIVE) {
    await replay(request, { action: "restart", speed: 64 });
    await replay(request, { action: "play" });
  }
  await openMissionControl(page);
  await expect(incidentCard(page, id)).toBeVisible({ timeout: 90_000 });
}

export function incidentCard(page: Page, id = "INC-0001") {
  return page.locator("article.card.incident").filter({ has: page.locator(".card-kind", { hasText: id }) });
}

export async function openIncident(page: Page, id = "INC-0001") {
  await incidentCard(page, id).click();
  const sheet = page.getByRole("dialog", { name: `Incident ${id}` });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("heading", { name: "What happened" })).toBeVisible();
  return sheet;
}
