import { defineConfig } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

const viewport = process.env.WSO_TVT_ACCOUNT_BROWSER_VIEWPORT;
if (viewport !== "account-desktop" && viewport !== "account-mobile") throw new Error("Use node scripts/test-tvt-account/server.mjs --browser for isolated viewport lifetimes");
const run = process.env.WSO_TVT_ACCOUNT_BROWSER_RUN_ID ??= randomUUID();
process.env.WSO_TVT_ACCOUNT_BROWSER_STATE_FILE ??= resolve("auth-state", `tvt-account-${run}`, "context.json");
process.env.WSO_TVT_ACCOUNT_BROWSER_OUTPUT ??= resolve("auth-state", `tvt-account-captures-${run}`);
export default defineConfig({
  testDir: "./tests/tvt_parity/e2e",
  testMatch: "login.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  // 60s startup + two 90s cases + 130s cleanup observer + margin.
  globalTimeout: 420_000,
  reporter: "list",
  globalSetup: "./scripts/test-tvt-account/server.mjs",
  outputDir: process.env.WSO_TVT_ACCOUNT_BROWSER_OUTPUT,
  use: { baseURL: "https://localhost:3543", browserName: "chromium", channel: "chrome", ignoreHTTPSErrors: true, trace: "off", video: "off", screenshot: "off" },
  projects: [
    { name: "account-desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "account-mobile", use: { viewport: { width: 390, height: 844 } } },
  ].filter((project) => project.name === viewport),
});
