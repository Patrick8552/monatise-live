const { test, expect } = require("@playwright/test");

test("command centre is usable without horizontal overflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Decision Command Center" })).toBeVisible();
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

test("market integrations clearly expand and collapse", async ({ page }) => {
  await page.goto("/coinglass-dashboard.html");
  const drawer = page.locator(".integration-drawer");
  const summary = page.getByText("Integrations & API keys", { exact: true });

  await expect(summary).toBeVisible();
  await expect(page.getByText("Click to expand and connect CoinGlass, alerts, voice, and AI")).toBeVisible();
  await expect(drawer).not.toHaveAttribute("open", "");
  await summary.click();
  await expect(drawer).toHaveAttribute("open", "");
  await expect(page.getByText("Your CoinGlass API key", { exact: true })).toBeVisible();
});
