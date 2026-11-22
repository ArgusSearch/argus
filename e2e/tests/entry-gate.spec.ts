import { expect, test } from "@playwright/test";

test("the welcome dialog isolates the app until the user enters", async ({ page }) => {
  await page.goto("/?fx=night&fxintro=0&entry=1");
  const workspace = page.locator("#root");
  const welcome = page.getByRole("dialog", { name: "Welcome to Mission Control" });
  const signIn = welcome.getByRole("button", { name: /^Sign in as / });

  await expect(welcome).toHaveClass(/\bshown\b/, { timeout: 30_000 });
  await expect(workspace).toHaveJSProperty("inert", true);
  await page.keyboard.press("Tab");
  await expect(signIn).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(welcome).toBeHidden();
  await expect(workspace).toHaveJSProperty("inert", false);
  await expect(page.getByRole("navigation", { name: "sections" })).toBeVisible();
});
