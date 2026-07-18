import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(TESTS_DIR, "..", "..");
const ORDERS_CSV = path.join(REPO_ROOT, "orders.csv");
const PAYMENTS_CSV = path.join(REPO_ROOT, "payments.csv");

// The hero screen pulls in Google Fonts and a remote Spline 3D scene purely for decoration.
// Blocking them keeps these tests fast and deterministic instead of depending on two
// third-party CDNs that have nothing to do with the auth/import/dashboard flow under test.
test.beforeEach(async ({ context }) => {
  await context.route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort());
  await context.route(/prod\.spline\.design/, (route) => route.abort());
});

async function signUp(page: import("@playwright/test").Page, email: string) {
  await page.goto("/");
  await expect(page.getByText("Revenue Audit").first()).toBeVisible();
  await page.getByRole("button", { name: "Sign Up" }).first().click();
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill("password123");
  await page.getByRole("button", { name: "Create Account" }).click();
  await expect(page.getByText("Import exports")).toBeVisible();
}

test("signup, import, dashboard, severity filter, and explain flow", async ({ page }) => {
  await signUp(page, `e2e-${Date.now()}@example.com`);

  const fileInputs = page.locator('input[type="file"]');
  await fileInputs.nth(0).setInputFiles(ORDERS_CSV);
  await fileInputs.nth(1).setInputFiles(PAYMENTS_CSV);
  await page.getByRole("button", { name: "Import" }).click();

  await expect(page.getByText("Imported 185 orders and 187 payments.")).toBeVisible();
  await expect(page.getByText("Total orders")).toBeVisible();
  await expect(page.getByText("Risk by type")).toBeVisible();
  await expect(page.getByText("Severity breakdown")).toBeVisible();
  await expect(page.getByText("22 visible of 22")).toBeVisible();

  // Click the Critical severity bar: it should filter the table and show a removable chip.
  await page.getByRole("button", { name: /Critical/ }).first().click();
  await expect(page.getByText(/visible of 22/)).toHaveText("17 visible of 22");
  await expect(page.locator(".active-filters")).toContainText("Critical");

  // Clear the filter via the chip's close button.
  await page.locator(".active-filters button").first().click();
  await expect(page.getByText(/visible of 22/)).toHaveText("22 visible of 22");

  // LLM explanation panel: loading -> some rendered result (real provider or deterministic fallback).
  await page.getByRole("button", { name: "Explain current view" }).click();
  await expect(page.locator(".explanation p").first()).toBeVisible({ timeout: 20_000 });
});

test("a failed dashboard fetch shows a retry action instead of spinning forever", async ({ page, context }) => {
  await signUp(page, `e2e-retry-${Date.now()}@example.com`);

  await context.route("**/api/dashboard", (route) => route.abort("connectionrefused"));
  await page.reload();

  await expect(page.getByText("Could not reach the server").or(page.getByText("Failed to fetch"))).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();

  await context.unroute("**/api/dashboard");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText("Import exports")).toBeVisible();
});

test("a second user cannot see the first user's imported data", async ({ page }) => {
  // Sequential signup/logout on one context, rather than two parallel browser contexts:
  // the per-user data isolation itself is exercised at the API layer by
  // backend/tests/test_auth.py::test_users_cannot_see_each_others_data. This test only
  // needs to confirm the dashboard *renders* the empty state for a brand-new account.
  await signUp(page, `e2e-owner-${Date.now()}@example.com`);
  const ownerFiles = page.locator('input[type="file"]');
  await ownerFiles.nth(0).setInputFiles(ORDERS_CSV);
  await ownerFiles.nth(1).setInputFiles(PAYMENTS_CSV);
  await page.getByRole("button", { name: "Import" }).click();
  await expect(page.getByText("Imported 185 orders and 187 payments.")).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await signUp(page, `e2e-intruder-${Date.now()}@example.com`);
  await expect(page.getByText("No data imported")).toBeVisible();
});
