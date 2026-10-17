import { expect, test } from "@playwright/test";
import type { MoverRow, MoversResponse } from "../../lib/api";

// Invented positions; never copy a user's holdings into a public fixture.
const row = (name: string, change = "1234567"): MoverRow => ({
  source: "stub", external_id: name, asset_type: "MF", name, symbol: null,
  basis: "price", start_price: "100", end_price: "105.1",
  start_value: "100000", end_value: "105100", change_abs: change,
  change_pct: change.startsWith("-") ? "-5.1" : "5.1", currency: "INR",
});
const payload: MoversResponse = {
  requested: { from: "2026-10-01", to: "2026-10-08" },
  compared: { from: "2026-10-02", to: "2026-10-08" },
  note: "No snapshot exists for the exact window asked for, so 2026-10-02 to 2026-10-08 was compared instead.",
  gainers: [row("Example India Small Cap Opportunities Fund - Direct Plan - Growth Option")],
  losers: [row("Example Diversified Equity Opportunities Fund Direct Growth", "-12345")],
  flows: [{ ...row("Example Savings Bank Account"), basis: "balance", change_pct: null }],
  opened: [row("Example Long Term Flexi Cap Fund Direct Growth")],
  closed: [row("Example Liquid Fund Direct Plan Growth Option")],
  excluded: [],
};

for (const width of [320, 375, 393, 430, 640, 768, 1280]) {
  for (const theme of ["light", "dark"]) {
    test(`${width}px ${theme}: movers stay inside the card with amounts shown and hidden`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.route("**/api/**", route => route.fulfill({ json: payload }));
      await page.goto(`/tests/browser/fixture/?theme=${theme}`);
      await expect(page.getByText(payload.gainers[0].name!)).toBeVisible();
      const card = page.locator(".bg-card").filter({ has: page.getByRole("heading", { name: "Top movers" }) });
      for (const masked of [false, true]) {
        if (masked) await page.getByRole("button", { name: "Toggle amounts" }).click();
        await expect(card.getByText(masked ? "+₹••••••" : "+₹12,34,567", { exact: true }).first()).toBeVisible();
        const sizes = await card.evaluate(el => {
          const bounds = el.getBoundingClientRect();
          return {
            viewport: document.documentElement.clientWidth,
            page: document.documentElement.scrollWidth,
            cardRight: bounds.right,
            // Check content bounds too: clipping overflow must not pass.
            contentRight: Math.max(...Array.from(el.querySelectorAll("li, li span, li b, button"), child => child.getBoundingClientRect().right)),
          };
        });
        expect(sizes.page, JSON.stringify(sizes)).toBeLessThanOrEqual(sizes.viewport);
        expect(sizes.contentRight).toBeLessThanOrEqual(sizes.cardRight - 1);
      }
    });
  }
}
