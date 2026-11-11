import path from "node:path";

// Playwright runs from the frontend directory.
export const DATA_DIR = path.resolve(process.cwd(), "e2e-data");
export const E2E_PASSWORD = "e2e-password";
export const E2E_EMAIL = "demo@example.com"; // the demo owner created by `app.seed --demo`
export const SHOTS_DIR = path.resolve(process.cwd(), "../docs/screenshots");
