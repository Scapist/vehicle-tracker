import path from "node:path";

// Playwright runs from the frontend directory.
export const DATA_DIR = path.resolve(process.cwd(), "e2e-data");
export const SHOTS_DIR = path.resolve(process.cwd(), "../docs/screenshots");
