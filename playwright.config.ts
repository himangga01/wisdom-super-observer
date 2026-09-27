import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/tvt_parity/e2e',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    headless: true,
    trace: 'off',
    screenshot: 'off',
  },
  projects: [
    { name: 'desktop-chrome', use: { browserName: 'chromium', channel: 'chrome' } },
    { name: 'desktop-edge', use: { browserName: 'chromium', channel: 'msedge' } },
  ],
});
