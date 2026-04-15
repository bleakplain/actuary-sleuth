import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:8000',
    trace: 'on-first-retry',
  },
  globalSetup: new URL('./e2e/global-setup.ts', import.meta.url).pathname,
  webServer: {
    command: 'npm run dev',
    port: 8000,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
