import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";

/**
 * The instant paint and its revalidation (issue #15).
 *
 * Navigating away from `/portfolio` and back unmounts the layout that holds the
 * provider, so the dashboard used to start from nothing every time: a spinner,
 * then a full walk of every bucket the portfolio has. The provider now keeps the
 * last successful load at module scope and repaints it on mount.
 *
 * Three properties make that safe rather than merely fast, and they are what is
 * pinned here:
 *
 * 1. **The paint is immediate** — the remembered reading is on screen in the
 *    first render, before any request resolves.
 * 2. **It is revalidated, and cheaply.** The summary is re-read; the expensive
 *    bucket walk is skipped only while the source's own `as_of` says nothing has
 *    moved.
 * 3. **A gate beats the memory.** If revalidation says this reader may not see
 *    the portfolio, the store is dropped and the gate renders — a signed-out tab
 *    must never keep showing the previous session's holdings.
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

import {
  PortfolioProvider,
  resetPortfolioMemory,
  usePortfolio,
} from "@/components/portfolio/PortfolioProvider";
import {
  PortfolioError,
  getPortfolioHistory,
  getPortfolioHoldings,
  getPortfolioSummary,
} from "@/lib/api";

const slice = (label: string, assetType: string, value: string) => ({
  label,
  asset_type: assetType,
  asset_type_raw: assetType,
  invested_amount: null,
  current_value: value,
  pnl: null,
  pnl_pct: null,
  weight_pct: "100.0",
  us_exposure: false,
  currency: "INR",
});

/** One bucket, so a full walk is a single call and the test stays quick. */
const summaryAt = (asOf: string, netWorth: string) => ({
  user_id: "local",
  source: "stub",
  as_of: asOf,
  currency: "INR",
  net_worth: netWorth,
  current_value: netWorth,
  invested_total: null,
  liabilities_total: "0.0",
  pnl: null,
  pnl_pct: null,
  by_asset_type: [slice("MF", "MF", netWorth)],
  by_asset_class: [],
  by_sector: [],
  by_market_cap: [],
  link_health: "linked" as const,
  last_captured_at: null,
});

const FIRST = summaryAt("2026-08-16T09:30:00+00:00", "1000000.0");

/** What the provider is holding, printed so the DOM can be asserted on. */
function Probe() {
  const { summary, buckets, loadingHoldings } = usePortfolio();
  return (
    <div>
      worth:{summary.net_worth} buckets:{buckets.length}{" "}
      {loadingHoldings ? "walking" : "idle"}
    </div>
  );
}

const mount = () =>
  render(
    <PortfolioProvider>
      <Probe />
    </PortfolioProvider>,
  );

/** Mount, and wait until the first load has finished its bucket walk. */
async function loadOnce() {
  const view = mount();
  await waitFor(() => expect(screen.getByText(/buckets:1 idle/)).toBeTruthy());
  return view;
}

beforeEach(() => {
  resetPortfolioMemory();
  vi.mocked(getPortfolioSummary).mockResolvedValue(FIRST as never);
  vi.mocked(getPortfolioHistory).mockResolvedValue({
    points: [],
    last_captured_at: null,
    days: 365,
    currency: "INR",
  } as never);
  vi.mocked(getPortfolioHoldings).mockResolvedValue({
    asset_type: "MF",
    currency: "INR",
    holdings: [],
  } as never);
});

describe("instant paint from the last known load", () => {
  it("renders the remembered portfolio before anything resolves", async () => {
    (await loadOnce()).unmount();

    // The remount's summary never settles, so anything on screen can only have
    // come from the store.
    vi.mocked(getPortfolioSummary).mockReturnValue(new Promise(() => {}) as never);
    mount();

    expect(screen.getByText(/worth:1000000.0/)).toBeTruthy();
    expect(screen.queryByText("Reading your portfolio…")).toBeNull();
  });

  it("revalidates the summary but does not re-walk an unchanged one", async () => {
    (await loadOnce()).unmount();
    const walkedOnce = vi.mocked(getPortfolioHoldings).mock.calls.length;

    await act(async () => {
      mount();
    });

    // The summary was re-read...
    expect(vi.mocked(getPortfolioSummary).mock.calls.length).toBe(2);
    // ...and it said nothing had moved, so the buckets were not fetched again.
    expect(vi.mocked(getPortfolioHoldings).mock.calls.length).toBe(walkedOnce);
    expect(screen.getByText(/buckets:1/)).toBeTruthy();
  });

  it("re-walks the buckets when the source's reading has moved", async () => {
    (await loadOnce()).unmount();
    const walkedOnce = vi.mocked(getPortfolioHoldings).mock.calls.length;

    vi.mocked(getPortfolioSummary).mockResolvedValue(
      summaryAt("2026-08-16T15:30:00+00:00", "1100000.0") as never,
    );
    mount();

    await waitFor(() =>
      expect(vi.mocked(getPortfolioHoldings).mock.calls.length).toBe(walkedOnce + 1),
    );
    await waitFor(() => expect(screen.getByText(/worth:1100000.0/)).toBeTruthy());
  });

  it("drops the memory and renders the gate when revalidation is refused", async () => {
    (await loadOnce()).unmount();

    vi.mocked(getPortfolioSummary).mockRejectedValue(
      new PortfolioError(409, "not_linked", "No usable IND Money link."),
    );
    const gated = mount();
    await waitFor(() =>
      expect(screen.getByText("Link your IND Money account")).toBeTruthy(),
    );
    gated.unmount();

    // And the store really is gone: the next mount starts from the spinner, not
    // from holdings this reader is no longer entitled to.
    vi.mocked(getPortfolioSummary).mockReturnValue(new Promise(() => {}) as never);
    mount();
    expect(screen.getByText("Reading your portfolio…")).toBeTruthy();
  });
});
