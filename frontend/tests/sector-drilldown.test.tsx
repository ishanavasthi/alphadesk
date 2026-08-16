import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";

/**
 * The sector drill-down race guard (card D1), ported from the manual DevTools
 * procedure in `docs/TESTING/D1.md` §9a.
 *
 * The failure it defends against: click the sector chips faster than the source
 * answers, and the *slowest* response wins — printing one asset type's sectors
 * under another's heading. On real money that is not a cosmetic glitch, it is a
 * false statement about what the reader owns. Reproducing it by hand needed
 * DevTools throttling and quick fingers; here the responses are deferred
 * promises and the race is resolved deliberately, in the wrong order, every run.
 *
 * The page is rendered for real, inside the same provider the route layout wraps
 * it in. Only `@/lib/api` is mocked, so the guard being tested (`chooseSector`'s
 * monotonic token + abort) is the shipped one.
 */

interface Deferred {
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
  signal?: AbortSignal;
}

/** Open drill-down requests, keyed by the asset type that was asked for. */
const pending = new Map<string, Deferred>();

// The page renders a locked state with sign-in off; force the flag on (card L1
// removed the admin-secret path this test used to rely on).
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

import PortfolioPage from "@/app/portfolio/page";
import {
  PortfolioProvider,
  resetPortfolioMemory,
} from "@/components/portfolio/PortfolioProvider";
import {
  getPortfolioAllocation,
  getPortfolioHistory,
  getPortfolioHoldings,
  getPortfolioSummary,
} from "@/lib/api";

const slice = (label: string, assetType: string | null, value: string) => ({
  label,
  asset_type: assetType,
  asset_type_raw: assetType,
  invested_amount: null,
  current_value: value,
  pnl: null,
  pnl_pct: null,
  weight_pct: "25.0",
  us_exposure: false,
  currency: "INR",
});

const SUMMARY = {
  user_id: "local",
  source: "stub",
  as_of: "2026-08-16T09:30:00+00:00",
  currency: "INR",
  net_worth: "1000000.0",
  current_value: "1000000.0",
  invested_total: null,
  liabilities_total: "0.0",
  pnl: null,
  pnl_pct: null,
  by_asset_type: [
    slice("MF", "MF", "500000.0"),
    slice("US_STOCK", "US_STOCK", "300000.0"),
    slice("FD", "FD", "200000.0"),
  ],
  by_asset_class: [],
  by_sector: [slice("Whole-portfolio Sector", null, "1000000.0")],
  by_market_cap: [],
  link_health: "linked" as const,
  last_captured_at: null,
};

function defer(assetType: string, signal?: AbortSignal): Promise<unknown> {
  return new Promise((resolve, reject) => {
    pending.set(assetType, { resolve, reject, signal });
  });
}

beforeEach(() => {
  pending.clear();
  // The provider remembers its last load at module scope (issue #15), so one
  // test's portfolio would otherwise paint inside the next one's.
  resetPortfolioMemory();
  vi.mocked(getPortfolioSummary).mockResolvedValue(SUMMARY as never);
  vi.mocked(getPortfolioHistory).mockResolvedValue({
    points: [],
    last_captured_at: null,
    days: 90,
    currency: "INR",
  } as never);
  vi.mocked(getPortfolioHoldings).mockResolvedValue({
    asset_type: "MF",
    currency: "INR",
    holdings: [],
  } as never);
  vi.mocked(getPortfolioAllocation).mockImplementation(
    ((assetType: string, _by: string, signal?: AbortSignal) =>
      defer(assetType, signal)) as never,
  );
});

/** Render and wait until the dashboard is past its loading state. */
async function renderDashboard() {
  const view = render(
    <PortfolioProvider>
      <PortfolioPage />
    </PortfolioProvider>,
  );
  await screen.findByText("Allocation by sector");
  return view;
}

const chip = (label: string) => screen.getByRole("button", { name: label });
const skeleton = () => document.querySelector('[aria-label="Loading allocation"]');

describe("sector drill-down race guard", () => {
  it("shows a skeleton rather than the outgoing bars while a chip is in flight", async () => {
    await renderDashboard();
    expect(screen.getByText("Whole-portfolio Sector")).toBeTruthy();

    await act(async () => {
      chip("Mutual funds").click();
    });

    // The previous card's content is gone the instant the chip is pressed —
    // bars that outlive their heading are the bug, not a nice-to-have.
    expect(skeleton()).toBeTruthy();
    expect(screen.queryByText("Whole-portfolio Sector")).toBeNull();
    expect(screen.getByText(/Within Mutual funds/)).toBeTruthy();
  });

  it("lets only the newest click write the card, whatever order responses land", async () => {
    await renderDashboard();

    await act(async () => {
      chip("Mutual funds").click();
    });
    const mfRequest = pending.get("MF")!;

    await act(async () => {
      chip("US stocks").click();
    });
    const usRequest = pending.get("US_STOCK")!;

    // The superseded request is aborted, exactly as the Network panel shows it
    // cancelled in the manual procedure.
    expect(mfRequest.signal?.aborted).toBe(true);
    expect(usRequest.signal?.aborted).toBe(false);

    // Now resolve them in the *wrong* order: the stale MF response arrives last
    // and would win in the unguarded version.
    await act(async () => {
      usRequest.resolve({
        source: "stub",
        asset_type: "US_STOCK",
        by: "sector",
        as_of: SUMMARY.as_of,
        currency: "INR",
        slices: [slice("US Technology", null, "300000.0")],
      });
    });
    await act(async () => {
      mfRequest.resolve({
        source: "stub",
        asset_type: "MF",
        by: "sector",
        as_of: SUMMARY.as_of,
        currency: "INR",
        slices: [slice("MF Financials", null, "500000.0")],
      });
    });

    await waitFor(() => expect(screen.getByText("US Technology")).toBeTruthy());
    // The heading and the bars agree, and the stale bucket never appears.
    expect(screen.getByText(/Within US stocks/)).toBeTruthy();
    expect(screen.queryByText("MF Financials")).toBeNull();
  });

  it("never renders whole-portfolio sectors under a `Within …` heading", async () => {
    await renderDashboard();
    await act(async () => {
      chip("Fixed deposits").click();
    });

    // While the drill-down is open the card must show the skeleton, not fall
    // back to the snapshot's portfolio-wide figures under an FD heading.
    expect(screen.getByText(/Within Fixed deposits/)).toBeTruthy();
    expect(screen.queryByText("Whole-portfolio Sector")).toBeNull();
    expect(skeleton()).toBeTruthy();
  });

  it("switches back to the whole portfolio instantly, and a late response cannot undo it", async () => {
    await renderDashboard();

    await act(async () => {
      chip("Mutual funds").click();
    });
    const mfRequest = pending.get("MF")!;

    await act(async () => {
      chip("Whole portfolio").click();
    });
    // No request: the whole-portfolio breakdown rides the snapshot call.
    expect(screen.getByText("Whole-portfolio Sector")).toBeTruthy();
    expect(screen.getByText(/Whole portfolio, as the snapshot reports it/)).toBeTruthy();
    expect(mfRequest.signal?.aborted).toBe(true);

    await act(async () => {
      mfRequest.resolve({
        source: "stub",
        asset_type: "MF",
        by: "sector",
        as_of: SUMMARY.as_of,
        currency: "INR",
        slices: [slice("MF Financials", null, "500000.0")],
      });
    });

    expect(screen.getByText("Whole-portfolio Sector")).toBeTruthy();
    expect(screen.queryByText("MF Financials")).toBeNull();
  });

  it("survives a burst of clicks and ends on the last one", async () => {
    await renderDashboard();

    for (const label of ["Mutual funds", "US stocks", "Fixed deposits", "Mutual funds"]) {
      await act(async () => {
        chip(label).click();
      });
    }

    // Resolve every request that was ever opened, oldest first — the worst case.
    const labels: Record<string, string> = {
      MF: "MF Financials",
      US_STOCK: "US Technology",
      FD: "FD Banks",
    };
    for (const [assetType, request] of pending) {
      await act(async () => {
        request.resolve({
          source: "stub",
          asset_type: assetType,
          by: "sector",
          as_of: SUMMARY.as_of,
          currency: "INR",
          slices: [slice(labels[assetType], null, "100000.0")],
        });
      });
    }

    await waitFor(() => expect(screen.getByText("MF Financials")).toBeTruthy());
    expect(screen.getByText(/Within Mutual funds/)).toBeTruthy();
    expect(screen.queryByText("US Technology")).toBeNull();
    expect(screen.queryByText("FD Banks")).toBeNull();
  });
});
