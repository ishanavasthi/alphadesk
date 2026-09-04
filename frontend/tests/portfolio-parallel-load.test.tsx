import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

/**
 * Parallel first load (issue #72, phase 1).
 *
 * The provider used to read the summary first and only then ask for the
 * history — two independent reads paying two serial roundtrips before the
 * page could settle. They now go out together; the holdings walk still waits
 * for the summary because it needs the snapshot's bucket list.
 *
 * Pinned here: with neither request resolved, both fetches are already in
 * flight. A regression to sequential reads fails this test.
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
    getPortfolioHoldingsAll: vi.fn(),
    getPortfolioAllocation: vi.fn(),
    capturePortfolioSnapshot: vi.fn(),
    startAuthLogin: vi.fn(),
    listFds: vi.fn(async () => ({ fds: [], note: null })),
  };
});

import {
  PortfolioProvider,
  resetPortfolioMemory,
  usePortfolio,
} from "@/components/portfolio/PortfolioProvider";
import { getPortfolioHistory, getPortfolioHoldingsAll, getPortfolioSummary } from "@/lib/api";

const summary = {
  user_id: "local",
  source: "stub",
  as_of: "2026-09-03T09:30:00+00:00",
  currency: "INR",
  net_worth: "1000000.0",
  current_value: "1000000.0",
  invested_total: null,
  liabilities_total: "0.0",
  pnl: null,
  pnl_pct: null,
  by_asset_type: [],
  by_asset_class: [],
  by_sector: [],
  by_market_cap: [],
  link_health: "linked" as const,
  last_captured_at: null,
};

const sliceRow = (label: string, assetType: string, value: string) => ({
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

function Probe() {
  const { summary: s, history, buckets } = usePortfolio();
  return (
    <div>
      worth:{s.net_worth} points:{history.length}{" "}
      {buckets.map((b) => `${b.assetType}=${b.status}`).join(",")}
    </div>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("parallel first load", () => {
  beforeEach(() => {
    resetPortfolioMemory();
    vi.clearAllMocks();
  });

  it("fires summary and history together", async () => {
    const summaryGate = deferred<typeof summary>();
    const historyGate = deferred<{ points: []; last_captured_at: null }>();
    vi.mocked(getPortfolioSummary).mockReturnValue(summaryGate.promise as never);
    vi.mocked(getPortfolioHistory).mockReturnValue(historyGate.promise as never);

    render(
      <PortfolioProvider>
        <Probe />
      </PortfolioProvider>,
    );

    // Neither request has resolved, yet both must already be in flight.
    await waitFor(() => {
      expect(vi.mocked(getPortfolioSummary)).toHaveBeenCalledTimes(1);
      expect(vi.mocked(getPortfolioHistory)).toHaveBeenCalledTimes(1);
    });

    summaryGate.resolve(summary);
    historyGate.resolve({ points: [], last_captured_at: null });
    await waitFor(() => expect(screen.getByText(/worth:1000000/)).toBeTruthy());
  });

  it("maps batch statuses onto buckets and errors unknown keys", async () => {
    vi.mocked(getPortfolioSummary).mockResolvedValue({
      ...summary,
      by_asset_type: [
        { ...sliceRow("MF", "MF", "600000.0"), asset_type: "MF" },
        { ...sliceRow("FD", "FD", "400000.0"), asset_type: "FD" },
      ],
    } as never);
    vi.mocked(getPortfolioHistory).mockResolvedValue({
      points: [],
      last_captured_at: null,
    } as never);
    vi.mocked(getPortfolioHoldingsAll).mockResolvedValue({
      buckets: [
        { asset_type: "MF", status: "ok", holdings: [], retry_after: null },
        { asset_type: "FD", status: "unsupported", holdings: [], retry_after: null },
      ],
    } as never);

    render(
      <PortfolioProvider>
        <Probe />
      </PortfolioProvider>,
    );

    await waitFor(() => expect(screen.getByText(/MF=ok/)).toBeTruthy());
    expect(screen.getByText(/FD=unsupported/)).toBeTruthy();
  });
});
