import fs from "node:fs";

import { defineConfig, devices } from "@playwright/test";

import { DATA_DIR, E2E_PASSWORD } from "./e2e/paths";
// workers re-evaluate this file while the server holds the DB open, so only the main process wipes it
if (!process.env.TEST_WORKER_INDEX) fs.rmSync(DATA_DIR, { recursive: true, force: true });

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  fullyParallel: false,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:8123" },
  webServer: {
    command:
      "uv run alembic upgrade head && uv run python -m app.seed --demo && uv run uvicorn app.main:app --port 8123",
    cwd: "../backend",
    url: "http://127.0.0.1:8123/healthz",
    // fake bot tokens only make the chat apps show up in Settings; NOTIFIER=log keeps the bots from starting
    env: { DATA_DIR, NOTIFIER: "log", DEMO_PASSWORD: E2E_PASSWORD, MCP_ENABLED: "true", TELEGRAM_BOT_TOKEN: "1:e2e",
      DISCORD_BOT_TOKEN: "e2e" },
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "wide", grep: /screenshots/, use: { viewport: { width: 1920, height: 1080 } } },
    { name: "mobile", use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 } },
  ],
});
