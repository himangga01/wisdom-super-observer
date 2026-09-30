import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e/auth",
  fullyParallel: false, workers: 1, retries: 0, timeout: 60_000, reporter: "list",
  use: { baseURL: "https://localhost:3443", ignoreHTTPSErrors: true, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "auth-chromium", use: { browserName: "chromium", channel: "chrome" } }],
  webServer: { command: "node scripts/test-auth/server.mjs", url: "https://localhost:3443", ignoreHTTPSErrors: true, reuseExistingServer: false, timeout: 120_000 },
});
