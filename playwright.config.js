const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./ui-tests",
  use: { baseURL: "http://127.0.0.1:4174", screenshot: "only-on-failure" },
  webServer: { command: "python3 -m http.server 4174 -d app", port: 4174, reuseExistingServer: true },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 13"], browserName: "chromium" } }
  ]
});
