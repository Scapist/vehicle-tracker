import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { DATA_DIR, E2E_EMAIL, E2E_PASSWORD, SHOTS_DIR } from "./paths";

const JPEG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.alloc(200, 1)]);
const PDF = Buffer.from("%PDF-1.4\n%test\n");
const shots = SHOTS_DIR;

function receiptFiles(): string[] {
  const root = path.join(DATA_DIR, "receipts");
  if (!fs.existsSync(root)) return [];
  return fs.readdirSync(root).flatMap((y) => fs.readdirSync(path.join(root, y)));
}

test("login page: wrong password, then sign in, then sign out", async ({ page }, info) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  fs.mkdirSync(shots, { recursive: true });
  await page.screenshot({ path: path.join(shots, `${info.project.name}-light-login-1.jpg`), type: "jpeg", quality: 60 });
  await page.getByLabel("Email").fill(E2E_EMAIL);
  await page.getByLabel("Password").fill("not-it");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Wrong email or password")).toBeVisible();
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.goto("/settings");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("invite link: new person signs up and sees only their own (empty) data", async ({ page, browser }, info) => {
  await page.request.post("/api/v1/auth/login", { data: { email: E2E_EMAIL, password: E2E_PASSWORD } });
  const invite = await (await page.request.post("/api/v1/auth/invites")).json();
  const guest = await browser.newContext({ viewport: page.viewportSize()! });
  const g = await guest.newPage();
  try {
    await g.goto(invite.link);
    await expect(g.getByRole("heading", { name: "Create your account" })).toBeVisible();
    await g.screenshot({ path: path.join(shots, `${info.project.name}-light-signup-1.jpg`), type: "jpeg", quality: 60 });
    await g.getByLabel("Your name").fill("Guest");
    await g.getByLabel("Email").fill(`guest-${info.project.name}-${Date.now()}@example.com`);
    await g.getByRole("textbox", { name: /^Password/ }).fill("guest-password-1");
    await g.getByLabel("Confirm password").fill("guest-password-1");
    await g.getByRole("button", { name: "Create account" }).click();
    await expect(g.getByText("No vehicles yet")).toBeVisible();
    await expect(g.getByText("Civic")).toHaveCount(0);
    expect((await g.request.get("/api/v1/vehicles/1")).status()).toBe(404);
  } finally {
    await guest.close();
  }
});

test.describe("signed in", () => {
  test.beforeEach(async ({ page }) => {
    const r = await page.request.post("/api/v1/auth/login", { data: { email: E2E_EMAIL, password: E2E_PASSWORD } });
    expect(r.ok()).toBe(true);
  });

test("dashboard loads with vehicle and alerts", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Civic" })).toBeVisible();
  await expect(page.getByText("Overdue").first()).toBeVisible();
});

test("log a service with JPEG and PDF receipts", async ({ page }, info) => {
  await page.goto("/vehicles/1");
  await expect(page.getByRole("heading", { name: "Civic" })).toBeVisible();
  await page.getByRole("button", { name: "Quick log" }).click();
  await page.getByRole("tab", { name: "Service", exact: true }).click();
  await page.getByRole("textbox", { name: "What was done?" }).click();
  await page.getByRole("option", { name: "Cabin filter" }).click();
  await page.keyboard.press("Escape"); // closes the dropdown only
  await page.getByLabel("Total cost").fill("45");
  await page.getByLabel("Shop / vendor").fill("E2E Garage");
  const input = page.locator('input[type="file"]').first();
  await input.setInputFiles([
    { name: "receipt.jpg", mimeType: "image/jpeg", buffer: JPEG },
    { name: "invoice.pdf", mimeType: "application/pdf", buffer: PDF },
  ]);
  await expect(page.getByText("receipt.jpg")).toBeVisible();
  const before = receiptFiles().length;
  await page.getByRole("button", { name: "Save service" }).click();
  await expect(page.getByText("Service logged for Civic")).toBeVisible();
  await expect.poll(() => receiptFiles().length).toBe(before + 2);
  expect(receiptFiles().some((f) => f.endsWith(".jpg"))).toBe(true);
  expect(receiptFiles().some((f) => f.endsWith(".pdf"))).toBe(true);
  await page.getByRole("tab", { name: "Services", exact: true }).click();
  await expect(page.getByText("E2E Garage").filter({ visible: true }).first()).toBeVisible();
  info.annotations.push({ type: "receipts", description: receiptFiles().join(",") });
});

test("mileage: lower value needs correction", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Quick log" }).click();
  await page.getByLabel("Odometer (km)").fill("1000");
  await page.getByRole("button", { name: "Save mileage" }).click();
  await expect(page.getByText("Lower than the current reading")).toBeVisible();
});

test("Quick log: switching vehicle does not keep the old vehicle's odometer", async ({ page }) => {
  const request = page.request;
  const nick = `Truck${Date.now()}`;
  const v = await (await request.post("/api/v1/vehicles", {
    data: { nickname: nick, make: "Ford", model: "F150", year: 2015 },
  })).json();
  await request.post(`/api/v1/vehicles/${v.id}/odometer`, { data: { km: 120000 } });
  try {
    await page.goto(`/vehicles/${v.id}`);
    await page.getByRole("button", { name: "Quick log" }).click();
    await page.getByRole("tab", { name: "Service", exact: true }).click();
    await expect(page.getByLabel("Odometer (km)")).toHaveValue("120,000");
    await page.getByRole("textbox", { name: "Vehicle" }).click();
    await page.getByRole("option", { name: "Civic" }).click();
    await expect(page.getByLabel("Odometer (km)")).not.toHaveValue("120,000");
    await expect(page.getByLabel("Odometer (km)")).toHaveValue(/^\d{2,3},\d{3}$/);
  } finally {
    await request.patch(`/api/v1/vehicles/${v.id}`, { data: { archived: true } });
  }
});

test("recurring payment counts toward spending and filters by category", async ({ page }) => {
  const request = page.request;
  const nick = `Lease${Date.now()}`;
  const v = await (await request.post("/api/v1/vehicles", {
    data: { nickname: nick, make: "Mazda", model: "3", year: 2024 },
  })).json();
  const year = new Date().getFullYear();
  try {
    await page.goto(`/vehicles/${v.id}`);
    await page.getByRole("tab", { name: "Payments", exact: true }).click();
    await page.getByRole("button", { name: "Add payment" }).click();
    await page.getByLabel("Name").fill("Lease");
    await page.getByRole("textbox", { name: "Category" }).fill("Financing");
    await page.getByLabel("Amount").fill("300");
    await page.getByLabel("First payment").fill(`January 1, ${year}`);
    await page.getByLabel("Name").click(); // closes the calendar (Escape would close the whole modal)
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("$300.00 / month").filter({ visible: true }).first()).toBeVisible();

    const month = new Date().getMonth() + 1; // Jan 1 .. this month's 1st have all happened
    await page.goto(`/reports?vehicle=${v.id}`);
    await expect(page.getByText((month * 300).toLocaleString("en-CA", { style: "currency", currency: "CAD" }))
      .filter({ visible: true }).first()).toBeVisible();
    await expect(page.getByText("Lease").filter({ visible: true }).first()).toBeVisible();

    await page.getByRole("textbox", { name: "Categories" }).click();
    await page.getByRole("option", { name: "Financing" }).click();
    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(/category=Financing/);

    // a payment entry leads to the vehicle's Payments tab
    await page.getByText("Lease", { exact: true }).filter({ visible: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/vehicles/${v.id}[?]tab=payments$`));
    await expect(page.getByRole("tab", { name: "Payments", selected: true })).toBeVisible();
  } finally {
    await request.patch(`/api/v1/vehicles/${v.id}`, { data: { archived: true } });
  }
});

test("a service that isn't in the list can be added while logging", async ({ page }, info) => {
  const name = `Rustproof ${info.project.name} ${Date.now()}`;
  await page.goto("/vehicles/1");
  await page.getByRole("button", { name: "Quick log" }).click();
  await page.getByRole("tab", { name: "Service", exact: true }).click();
  const picker = page.getByRole("textbox", { name: "What was done?" });
  await picker.fill(name);
  await page.getByRole("option", { name: `+ Add “${name}”` }).click();
  await expect(page.getByText(name, { exact: true }).filter({ visible: true }).first()).toBeVisible();
  await page.keyboard.press("Escape"); // closes the dropdown only
  await page.getByLabel("Total cost").fill("90");
  await page.getByRole("button", { name: "Save service" }).click();
  await expect(page.getByText("Service logged for Civic")).toBeVisible();
  await page.goto("/settings");
  await expect(page.getByText(name, { exact: true })).toBeVisible();
});

test("a service entry in Reports opens its details", async ({ page }) => {
  await page.goto("/reports?period=12-months");
  await page.getByText("Garage Pro").filter({ visible: true }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByText("Garage Pro").first()).toBeVisible();
});

test("a logged service can be edited and deleted", async ({ page }, info) => {
  const vendor = `Edit-me ${info.project.name}`;
  const r = await page.request.post("/api/v1/services", {
    multipart: { vehicle_id: "1", date: "2026-11-01", cost_cents: "5000", vendor },
  });
  expect(r.ok()).toBe(true);
  await page.goto("/vehicles/1");
  await page.getByRole("tab", { name: "Services", exact: true }).click();
  await page.getByText(vendor).filter({ visible: true }).first().click();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Shop / vendor").fill(`${vendor} fixed`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Service updated")).toBeVisible();
  await expect(page.getByRole("dialog").getByText(`${vendor} fixed`)).toBeVisible();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("button", { name: "Delete, including receipts" }).click();
  await expect(page.getByText("Service deleted")).toBeVisible();
  await expect(page.getByText(`${vendor} fixed`).filter({ visible: true })).toHaveCount(0);
});

test("winter-tire reminders can't be added twice", async ({ page }) => {
  await page.goto("/vehicles/1");
  await page.getByRole("tab", { name: "Reminders", exact: true }).click();
  await expect(page.getByText("Install winter tires by Dec 1")).toBeVisible(); // the demo car has them
  await expect(page.getByRole("button", { name: "Add winter-tire reminders" })).toHaveCount(0);
});

test("mileage nudge can be set per vehicle", async ({ page }) => {
  const request = page.request;
  const v = await (await request.post("/api/v1/vehicles", {
    data: { nickname: `Nudge${Date.now()}`, make: "Kia", model: "Soul", year: 2018 },
  })).json();
  try {
    await page.goto(`/vehicles/${v.id}?tab=odometer`);
    const select = page.getByRole("textbox", { name: "Ask me for the km" });
    await expect(select).toHaveValue("After 2 weeks");
    await select.click();
    await page.getByRole("option", { name: "Never" }).click();
    await expect.poll(async () => (await (await request.get(`/api/v1/vehicles/${v.id}`)).json()).nudge_days).toBe(0);
  } finally {
    await request.patch(`/api/v1/vehicles/${v.id}`, { data: { archived: true } });
  }
});

test("chat apps: Discord shows its own link command next to Telegram", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByText("Chat apps", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Connect Discord" }).click();
  await expect(page.getByText(/^!link [A-Z0-9]{8}$/)).toBeVisible();
  await expect(page.getByText("as a direct message", { exact: false })).toBeVisible();
});

test("AI assistants: create a token, see the setup, revoke it", async ({ page }) => {
  await page.goto("/settings");
  const name = `E2E ${Date.now()}`;
  await page.getByLabel("New token for").fill(name);
  await page.getByRole("button", { name: "Create token" }).click();
  const token = (await page.getByTestId("new-token").textContent()) ?? "";
  expect(token).toMatch(/^vt_/);
  await expect(page.getByText(`Bearer ${token}`, { exact: false }).first()).toBeVisible();
  // the token works against /mcp; a wrong one doesn't
  const call = (t: string) => page.request.post("/mcp", {
    headers: { Authorization: `Bearer ${t}`, Accept: "application/json, text/event-stream",
      "mcp-protocol-version": "2025-06-18" },
    data: { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "list_vehicles", arguments: {} } },
  });
  expect((await call("vt_nope")).status()).toBe(401);
  const ok = await call(token);
  expect(ok.status()).toBe(200);
  expect(JSON.stringify(await ok.json())).toContain("Civic");
  const row = page.locator("div").filter({ has: page.getByText(name, { exact: true }) })
    .filter({ has: page.getByRole("button", { name: "Revoke" }) }).last();
  await row.getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByText(name, { exact: true })).toHaveCount(0);
  expect((await call(token)).status()).toBe(401);
});

for (const scheme of ["light", "dark"] as const) {
  test(`screenshots (${scheme})`, async ({ page }, info) => {
    await page.emulateMedia({ colorScheme: scheme });
    fs.mkdirSync(shots, { recursive: true });
    const prefix = `${info.project.name}-${scheme}`;
    // viewport-sized JPEGs at scroll positions, so fixed bars look as a user sees them
    const snap = async (name: string, maxSegments = 3) => {
      await page.waitForLoadState("networkidle");
      await page.evaluate(() => window.scrollTo(0, 0));
      const vh = page.viewportSize()!.height;
      const total = await page.evaluate(() => document.documentElement.scrollHeight);
      const segs = Math.min(maxSegments, Math.max(1, Math.ceil(total / vh)));
      for (let i = 0; i < segs; i++) {
        await page.evaluate((y) => window.scrollTo(0, y), i * (vh - 80));
        await page.waitForTimeout(150);
        await page.screenshot({ path: path.join(shots, `${prefix}-${name}-${i + 1}.jpg`), type: "jpeg", quality: 60 });
      }
    };
    const go = async (route: string) => page.goto(route);
    await go("/"); await snap("dashboard", 1);
    await go("/vehicles/1"); await snap("vehicle");
    await page.getByRole("tab", { name: "Services", exact: true }).click(); await snap("vehicle-services", 2);
    await page.getByRole("tab", { name: "Reminders", exact: true }).click(); await snap("vehicle-reminders", 3);
    await page.getByRole("tab", { name: "Payments", exact: true }).click(); await snap("vehicle-payments", 1);
    await page.getByRole("tab", { name: "Odometer", exact: true }).click(); await snap("vehicle-odometer", 1);
    await go("/tires"); await snap("tires", 2);
    await go("/reports"); await snap("reports", 2);
    await go("/settings"); await snap("settings", 4);
    await go("/vehicles"); await snap("vehicles", 1);
    await go("/");
    await page.getByRole("button", { name: "Quick log" }).click();
    await page.getByRole("tab", { name: "Service", exact: true }).click();
    await snap("quicklog-service", 1);
  });
}
});
