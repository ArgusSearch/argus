import { expect, test } from "@playwright/test";

test("settings fields have browser identifiers as well as labels", async ({ page }) => {
  await page.goto("/?fx=night&fxintro=0&view=settings&tab=account");
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toHaveAttribute("name", "name");
  await expect(page.getByRole("textbox", { name: "Email", exact: true })).toHaveAttribute("name", "email");

  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: "Quiet hours" }).click();
  await expect(page.getByRole("textbox", { name: "Timezone" })).toHaveAttribute("name", "timezone");
  await expect(page.getByRole("spinbutton", { name: "Page anyway above" })).toHaveAttribute("id", /.+/);
});
