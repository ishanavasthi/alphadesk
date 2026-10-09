import { expect, test, type Page } from "@playwright/test";

async function expectDocumentTheme(page: Page, theme: "light" | "dark") {
  const surface = page.locator("#adp-root");
  if (theme === "dark") await expect(surface).toHaveAttribute("data-adp-theme", "dark");
  else await expect(surface).not.toHaveAttribute("data-adp-theme", "dark");
  const ground = await surface.evaluate(el => getComputedStyle(el).backgroundColor);
  await expect(page.locator("html")).toHaveCSS("background-color", ground);
  await expect(page.locator("body")).toHaveCSS("background-color", ground);
  await expect(page.locator("html")).toHaveCSS("color-scheme", theme);
}

test.use({ viewport: { width: 393, height: 852 } });

test("document ground follows stored theme, toggles and surface remounts", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.addInitScript(() => localStorage.setItem("adp-theme", "dark"));
  await page.goto("/tests/browser/fixture/theme.html");
  await expectDocumentTheme(page, "dark");
  await page.getByRole("button", { name: "Remount surface" }).click();
  await expectDocumentTheme(page, "dark");
  await page.getByRole("button", { name: "Switch between light and dark" }).click();
  await expectDocumentTheme(page, "light");
  await page.getByRole("button", { name: "Switch between light and dark" }).click();
  await expectDocumentTheme(page, "dark");
});

test("document ground follows system theme without a stored override", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/tests/browser/fixture/theme.html");
  await expectDocumentTheme(page, "dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expectDocumentTheme(page, "light");
});

test("normal vertical scrolling works while document overscroll is suppressed", async ({ page }) => {
  await page.goto("/tests/browser/fixture/theme.html");
  await expect(page.getByText("Scrollable themed surface")).toBeVisible();
  await expect(page.locator("html")).toHaveCSS("overscroll-behavior-y", "none");
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const bounds = await page.evaluate(() => ({
    top: window.scrollY,
    bottom: window.scrollY + window.innerHeight,
    height: document.documentElement.scrollHeight,
    width: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(bounds.top).toBeGreaterThan(0);
  expect(Math.abs(bounds.bottom - bounds.height)).toBeLessThanOrEqual(1);
  expect(bounds.width).toBeLessThanOrEqual(bounds.viewport);
});
