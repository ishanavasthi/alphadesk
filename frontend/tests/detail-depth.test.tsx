import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";

/**
 * The drill-down depth added by issue #7: a per-holding dialog and the
 * Performance window chips.
 *
 * Both are places where it would be easy to invent a number — a missing cost
 * basis rendered as a −100% return, or a window's "change" stated from a single
 * captured day. The assertions below are mostly about what does *not* appear.
 *
 * As with the drill-down suite, only `@/lib/api` is mocked: the pages render
 * inside the real provider, so the arithmetic under test is the shipped one.
 */

vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return { ...actual, AUTH_ENABLED: true };
});

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getPortfolioSummary: vi.fn(),
    getPortfolioHistory: vi.fn(),
    getPortfolioHoldings: vi.fn(),
    getPortfolioAllocation: vi.fn(),
    capturePortfolioSnapshot: vi.fn(),
    startAuthLogin: vi.fn(),
  };
});

import PortfolioHoldingsPage from "@/app/portfolio/holdings/page";
import PortfolioPerformancePage from "@/app/portfolio/performance/page";
import { PortfolioProvider } from "@/components/portfolio/PortfolioProvider";
import {
  getPortfolioHistory,
  getPortfolioHoldings,
  getPortfolioSummary,
} from "@/lib/api";

const SUMMARY = {
  user_id: "local",
  source: "stub",
  as_of: "2026-08-16T09:30:00+00:00",
  currency: "INR",
  net_worth: "1000000.0",
  current_value: "1000000.0",
  invested_total: "500000.0",
  liabilities_total: "0.0",
  pnl: null,
  pnl_pct: null,
  by_asset_type: [
    {
      label: "MF",
      asset_type: "MF",
      asset_type_raw: "MF",
      invested_amount: "500000.0",
      current_value: "1000000.0",
      pnl: null,
      pnl_pct: null,
      weight_pct: "100.0",
      us_exposure: false,
      currency: "INR",
    },
  ],
  by_asset_class: [],
  by_sector: [],
  by_market_cap: [],
  link_health: "linked" as const,
  last_captured_at: null,
};

/** A holding with a full cost basis, and one the source reported without one. */
const WITH_BASIS = {
  source: "ind_money",
  external_id: "INDS00577",
  asset_type: "MF",
  asset_type_raw: "MF",
  symbol: "DEMOFUND",
  name: "Demo Growth Fund",
  isin: "INF000DEMO01",
  units: "1250.5",
  avg_cost: "400.0",
  invested_amount: "500000.0",
  current_price: "480.0",
  current_value: "600000.0",
  pnl: "100000.0",
  pnl_pct: "20.0",
  us_exposure: false,
  currency: "INR",
  as_of: SUMMARY.as_of,
};

const NO_BASIS = {
  ...WITH_BASIS,
  external_id: "INDS00901",
  symbol: null,
  name: "Demo Provident Balance",
  isin: null,
  units: null,
  avg_cost: null,
  invested_amount: null,
  current_price: null,
  current_value: "400000.0",
  pnl: null,
  pnl_pct: null,
};

const point = (date: string, netWorth: string) => ({ date, net_worth: netWorth });

beforeEach(() => {
  vi.mocked(getPortfolioSummary).mockResolvedValue(SUMMARY as never);
  vi.mocked(getPortfolioHistory).mockResolvedValue({
    points: [],
    last_captured_at: null,
    days: 365,
    currency: "INR",
  } as never);
  vi.mocked(getPortfolioHoldings).mockResolvedValue({
    asset_type: "MF",
    currency: "INR",
    holdings: [WITH_BASIS, NO_BASIS],
  } as never);
});

async function renderHoldings() {
  render(
    <PortfolioProvider>
      <PortfolioHoldingsPage />
    </PortfolioProvider>,
  );
  await screen.findByText("Demo Growth Fund");
}

async function renderPerformance() {
  render(
    <PortfolioProvider>
      <PortfolioPerformancePage />
    </PortfolioProvider>,
  );
  await screen.findByRole("button", { name: "90D" });
}

/**
 * The dialog's `<dd>` for one label, so a `—` can be attributed to its field.
 *
 * Scoped to the dialog on purpose: several of these labels ("Units",
 * "Invested", "Return") are also column headers in the table behind it.
 */
function detail(label: string): HTMLElement {
  const term = within(screen.getByRole("dialog")).getByText(label);
  return term.parentElement!.querySelector("dd") as HTMLElement;
}

describe("per-holding detail dialog", () => {
  it("opens from a row click with every figure the row carried", async () => {
    await renderHoldings();

    await act(async () => {
      screen.getByRole("button", { name: "Details for Demo Growth Fund" }).click();
    });

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Demo Growth Fund");
    expect(dialog.textContent).toContain("DEMOFUND · INF000DEMO01 · INDS00577");
    expect(detail("Units").textContent).toBe("1,250.5");
    expect(detail("Average cost").textContent).toBe("₹400");
    expect(detail("Invested").textContent).toBe("₹5,00,000");
    expect(detail("Current value").textContent).toBe("₹6,00,000");
    expect(detail("Return").textContent).toContain("+₹1,00,000");
    expect(detail("Return").textContent).toContain("+20.0%");
    // 6,00,000 of the snapshot's own 10,00,000 current value.
    expect(detail("Share of portfolio").textContent).toContain("60.00%");
  });

  it("labels every gap on a row the source reported without a cost basis", async () => {
    await renderHoldings();

    await act(async () => {
      screen.getByRole("button", { name: "Details for Demo Provident Balance" }).click();
    });

    await screen.findByRole("dialog");
    expect(detail("Units").textContent).toBe("—");
    expect(detail("Average cost").textContent).toBe("—");
    expect(detail("Invested").textContent).toBe("—");
    // The whole point: no invented zero, and no −100% conjured from a missing
    // basis against a real current value.
    expect(detail("Return").textContent).toContain("—");
    expect(detail("Return").textContent).toContain("no cost basis reported");
    expect(detail("Return").textContent).not.toContain("100.0%");
    // Sector and cap band are portfolio-level slices, never per holding.
    expect(detail("Sector").textContent).toContain("—");
    expect(detail("Cap band").textContent).toContain("—");
  });

  it("opens on Enter, so the rows are reachable without a mouse", async () => {
    await renderHoldings();

    const row = screen.getByRole("button", { name: "Details for Demo Growth Fund" });
    expect(row.getAttribute("tabindex")).toBe("0");
    await act(async () => {
      row.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }),
      );
    });

    expect((await screen.findByRole("dialog")).textContent).toContain("Demo Growth Fund");
  });
});

describe("performance windows", () => {
  it("slices the fetched history and states the change over the chosen window", async () => {
    vi.mocked(getPortfolioHistory).mockResolvedValue({
      points: [
        point("2026-01-15", "800000.0"),
        point("2026-06-10", "900000.0"),
        point("2026-08-01", "950000.0"),
        point("2026-08-16", "1000000.0"),
      ],
      last_captured_at: "2026-08-16T18:15:00+00:00",
      days: 365,
      currency: "INR",
    } as never);

    await renderPerformance();

    // The year is fetched once; the chips are slices of it, not new requests.
    await waitFor(() => expect(vi.mocked(getPortfolioHistory)).toHaveBeenCalledWith(365, expect.anything()));

    // 90D is the default: 2026-06-10 → 2026-08-16.
    await screen.findByText(/2026-06-10 → 2026-08-16/);
    expect(screen.getByText("+₹1,00,000 · +11.11%")).toBeTruthy();

    await act(async () => {
      screen.getByRole("button", { name: "30D" }).click();
    });
    expect(screen.getByText(/2026-08-01 → 2026-08-16/)).toBeTruthy();
    expect(screen.getByText("+₹50,000 · +5.26%")).toBeTruthy();

    await act(async () => {
      screen.getByRole("button", { name: "1Y" }).click();
    });
    expect(screen.getByText(/2026-01-15 → 2026-08-16/)).toBeTruthy();
    expect(screen.getByText("+₹2,00,000 · +25.00%")).toBeTruthy();
  });

  it("states a window it cannot subtract instead of inventing a change", async () => {
    vi.mocked(getPortfolioHistory).mockResolvedValue({
      points: [point("2026-01-15", "800000.0"), point("2026-08-16", "1000000.0")],
      last_captured_at: "2026-08-16T18:15:00+00:00",
      days: 365,
      currency: "INR",
    } as never);

    await renderPerformance();

    // 90D holds only the last point — one reading is not a change.
    expect(screen.getByText(/Not enough captured days in this window/)).toBeTruthy();

    await act(async () => {
      screen.getByRole("button", { name: "1Y" }).click();
    });
    expect(screen.getByText("+₹2,00,000 · +25.00%")).toBeTruthy();
  });
});
