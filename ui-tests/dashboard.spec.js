const { test, expect } = require("@playwright/test");

test("command centre is usable without horizontal overflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("link", { name: "Build Signal" })).toBeVisible();
  await expect(page.getByLabel("Signal performance filters")).toBeAttached();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBeFalsy();
});

test("primary navigation has no duplicate crypto trainer entry", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "primary navigation" }).getByText("Crypto Trainer")).toHaveCount(1);
  await expect(page.getByRole("navigation", { name: "desk sections" }).getByText("Crypto Trainer")).toHaveCount(0);
});
