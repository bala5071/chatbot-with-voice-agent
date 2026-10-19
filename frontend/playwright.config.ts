import { defineConfig } from "@playwright/test";

// Smoke tests of the built page, served by the real chat backend, with the fake gateway
// (backend/tests/fake_gateway.py) behind it, so no model and no gateway are needed.
// `npm run e2e` builds the page first; both servers are started here.
//
// PLAYWRIGHT_CHANNEL=chrome uses the Chrome already installed instead of the browser
// `npx playwright install chromium` downloads.

const GATEWAY_PORT = 8199;
const CHAT_PORT = 8198;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "*.e2e.ts",
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: "./e2e/results",
  use: {
    baseURL: `http://127.0.0.1:${CHAT_PORT}`,
    channel: process.env.PLAYWRIGHT_CHANNEL,
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `uv run uvicorn tests.fake_gateway:create_fake_gateway --factory --port ${GATEWAY_PORT} --log-level warning`,
      cwd: "../backend",
      url: `http://127.0.0.1:${GATEWAY_PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `uv run uvicorn gateway_chat.app:create_default_app --factory --port ${CHAT_PORT} --log-level warning`,
      cwd: "../backend",
      env: { GATEWAY_URL: `http://127.0.0.1:${GATEWAY_PORT}` },
      url: `http://127.0.0.1:${CHAT_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
