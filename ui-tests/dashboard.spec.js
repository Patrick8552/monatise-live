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

test("production grid analysis renders validated two-sided levels and risk issues", async ({ page }) => {
  await page.route("**/api/public/analysis?*", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      ok: true,
      analysis: {
        classification: "grid",
        status: "blocked",
        blocked_by: "risk_validation",
        completed_stages: 12,
        grid_score: 8,
        conviction: 0.75,
        risk_decision: "rejected",
        risk_validation_invoked: true,
        execution_policy_produced: false,
        grid_plan: {
          center: 100,
          buy_levels: [99, 98, 97],
          sell_levels: [101, 102, 103],
          lower_invalidation: 96,
          upper_invalidation: 104,
          levels_per_side: 3
        },
        risk_issues: [{ severity: "blocker", message: "regime is unstable" }],
        reasons: ["two-sided liquidity favors grid logic"]
      }
    })
  }));

  await page.goto("/coinglass-dashboard.html");

  const production = page.locator("#hyperList");
  await expect(production).toContainText("GRID CANDIDATE · RISK BLOCKED");
  await expect(production).toContainText("$99.00 / $98.00 / $97.00");
  await expect(production).toContainText("$101.00 / $102.00 / $103.00");
  await expect(production).toContainText("Below $96.00 or above $104.00");
  await expect(production).toContainText("regime is unstable");
});
