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

test("production grid analysis renders projected decision-ready levels without a risk gate", async ({ page }) => {
  await page.route("**/api/public/analysis?*", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      ok: true,
      analysis: {
        classification: "grid",
        status: "completed",
        blocked_by: null,
        completed_stages: 13,
        grid_score: 8,
        conviction: 0.75,
        grid_plan: {
          center: 100,
          buy_levels: [99, 98, 97],
          sell_levels: [101, 102, 103],
          lower_invalidation: 96,
          upper_invalidation: 104,
          levels_per_side: 3
        },
        reasons: ["two-sided liquidity favors grid logic"]
      }
    })
  }));

  await page.goto("/coinglass-dashboard.html");

  const production = page.locator("#hyperList");
  await expect(production).toContainText("GRID DECISION READY");
  await expect(production).toContainText("Projected decision geometry");
  await expect(production).toContainText("$99.00 / $98.00 / $97.00");
  await expect(production).toContainText("$101.00 / $102.00 / $103.00");
  await expect(production).toContainText("Below $96.00 or above $104.00");
  await expect(production).not.toContainText("RISK BLOCKED");
  await expect(production).not.toContainText("Risk review");

  const generated = page.locator("article").filter({ has: page.getByRole("heading", { name: "Monatise Generated Signals" }) });
  await expect(generated).toContainText("GRID · DECISION READY");
  await expect(generated).toContainText("Grid bids");
  await expect(generated).toContainText("Grid offers");
  await expect(generated).not.toContainText("WAIT · NO TRADE");

  const framework = page.locator("article").filter({ has: page.getByRole("heading", { name: "Monatise Framework" }) });
  await expect(framework).toContainText("GRID");
  await expect(framework).toContainText("Decision Ready");
  await expect(framework).not.toContainText("BUY\n");
});

test("rapid asset switching never renders analysis from the previous asset", async ({ page }) => {
  await page.route("**/api/public/analysis?*", async (route) => {
    const symbol = new URL(route.request().url()).searchParams.get("symbol");
    if (symbol === "BTC") await new Promise((resolve) => setTimeout(resolve, 500));
    const center = symbol === "ETH" ? 1900 : 65000;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        analysis: {
          symbol,
          classification: "grid",
          direction: "two_sided",
          status: "completed",
          blocked_by: null,
          completed_stages: 13,
          grid_score: 8,
          conviction: 0.75,
          grid_plan: {
            center,
            buy_levels: [center - 10, center - 20, center - 30],
            sell_levels: [center + 10, center + 20, center + 30],
            lower_invalidation: center - 40,
            upper_invalidation: center + 40,
            levels_per_side: 3
          },
          reasons: ["two-sided liquidity favors grid logic"]
        }
      })
    });
  });

  await page.goto("/coinglass-dashboard.html");
  await page.locator("#assetSelect").selectOption("ETH");

  const production = page.locator("#hyperList");
  await expect(production).toContainText("$1,900", { timeout: 10_000 });
  await expect(production).not.toContainText("$65,000");
  await expect(page.locator("#assetSelect")).toHaveValue("ETH");
});

test("long liquidation errors wrap without mobile overflow", async ({ page }) => {
  await page.setViewportSize({ width: 327, height: 800 });
  await page.goto("/coinglass-dashboard.html");
  await page.locator("#maxPain").evaluate((element) => {
    element.textContent = "CoinGlass liquidation map returned no price levels because the upstream service is temporarily unavailable";
  });

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBeFalsy();
});
