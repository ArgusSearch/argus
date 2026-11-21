import { expect, test } from "@playwright/test";
import { LIVE, openIncident, runToIncident, watchErrors } from "./helpers";

test("clicking a number opens its receipt with SQL and as_of; re-run behaves per mode", async ({ page, request }) => {
  const errors = watchErrors(page);
  await runToIncident(page, request);
  const sheet = await openIncident(page);

  const num = sheet.locator("button.num").first();
  await expect(num).toBeVisible();
  const title = (await num.getAttribute("title")) ?? "";
  const id = /receipt (r\d+)/.exec(title)?.[1];
  expect(id, `receipt id in title "${title}"`).toBeTruthy();
  await num.click();

  const drawer = page.getByRole("dialog", { name: `Receipt ${id}` });
  await expect(drawer).toBeVisible();
  await expect(drawer.locator("pre.sql")).toContainText("SELECT");
  await expect(drawer.getByText("as_of (pinned)")).toBeVisible();
  await expect(drawer.locator(".facts")).toContainText(/\d\d:\d\d/);

  await drawer.getByRole("button", { name: "Re-run SQL" }).click();
  if (LIVE) {
    await expect(drawer.locator(".verify.ok")).toContainText("✓ Same hash", { timeout: 20_000 });
    await expect(drawer.locator(".verify.bad")).toHaveCount(0);
  } else {
    // replay has no world to query: the API answers 409 by design and the drawer says so
    await expect(drawer.locator(".modal-foot .verify")).not.toContainText("Runs the exact SQL again", { timeout: 10_000 });
    await expect(drawer.locator(".verify.ok")).toHaveCount(0);
  }
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  // replay: the documented 409 on /rerun shows up as one http line and one console line
  const allowed = (e: string) => !LIVE && (e.includes("409 (Conflict)") || (e.startsWith("http 409") && e.includes("/rerun")));
  expect(errors().filter((e) => !allowed(e))).toEqual([]);
});
