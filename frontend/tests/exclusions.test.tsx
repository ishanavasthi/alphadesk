import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { HoldingExclusion, PortfolioHolding, PortfolioSummary } from "@/lib/api";
import { applyExclusions } from "@/components/portfolio/exclusions";
import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { StatCards } from "@/components/portfolio/StatCards";

/**
 * Excluding holdings from the figures (#65 follow-up). The rows are the ones
 * from the issue: two vendor FDs reported at a fraction of their principal,
 * which the reader re-entered by hand and wants out of every number.
 */

function holding(
  external_id: string,
  asset_type: string,
  current: string,
  invested: string | null,
  extra: Partial<PortfolioHolding> = {},
): PortfolioHolding {
  return {
    source: "ind_money",
    external_id,
    asset_type,
    asset_type_raw: asset_type,
    symbol: null,
    name: "Kotak Mahindra Bank Limited",
    isin: null,
    units: null,
    avg_cost: null,
    invested_amount: invested,
    current_price: null,
    current_value: current,
    pnl: null,
    pnl_pct: null,
    us_exposure: false,
    currency: "INR",
    as_of: "2026-11-10T00:00:00+00:00",
    note: null,
    ...extra,
  };
}

const FD_A = holding("FD:A", "FD", "171", "10000", { note: "stale source record" });
const FD_B = holding("FD:B", "FD", "162", "5000", { note: "stale source record" });
const FUND = holding("MF:X", "MF", "120000", "100000", { name: "Index Fund" });

function exclusion(external_id: string): HoldingExclusion {
  return {
    id: `ex-${external_id}`,
    source: "ind_money",
    external_id,
    asset_type: "FD",
    name: "Kotak Mahindra Bank Limited",
    created_at: "2026-11-10T00:00:00+00:00",
  };
}

const slice = (asset_type: string, current: string, invested: string, weight: string) => ({
  label: asset_type,
  asset_type,
  asset_type_raw: asset_type,
  invested_amount: invested,
  current_value: current,
  pnl: null,
  pnl_pct: null,
  weight_pct: weight,
  us_exposure: false,
  currency: "INR",
});

const SUMMARY: PortfolioSummary = {
  user_id: "u",
  source: "ind_money",
  as_of: "2026-11-10T00:00:00+00:00",
  currency: "INR",
  net_worth: "120333.00",
  current_value: "120333.00",
  invested_total: "115000.00",
  liabilities_total: null,
  pnl: "5333.00",
  pnl_pct: "4.64",
  by_asset_type: [
    slice("MF", "120000.00", "100000.00", "99.72"),
    slice("FD", "333.00", "15000.00", "0.28"),
  ],
  by_asset_class: [],
  by_sector: [],
  by_market_cap: [],
  link_health: "linked",
  last_captured_at: null,
};

describe("applyExclusions", () => {
  it("is the identity with nothing excluded", () => {
    const result = applyExclusions(SUMMARY, [FD_A, FD_B, FUND], []);
    expect(result.summary).toBe(SUMMARY);
    expect(result.removedCount).toBe(0);
  });

  it("takes both FDs out of every headline figure and the allocation", () => {
    const result = applyExclusions(SUMMARY, [FD_A, FD_B, FUND], [
      exclusion("FD:A"),
      exclusion("FD:B"),
    ]);
    expect(result.removedCount).toBe(2);
    expect(result.removedValue).toBe(333);
    expect(result.removedInvested).toBe(15000);
    expect(result.summary.net_worth).toBe("120000.00");
    expect(result.summary.current_value).toBe("120000.00");
    expect(result.summary.invested_total).toBe("100000.00");
    expect(result.summary.pnl).toBe("20000.00");
    expect(result.summary.pnl_pct).toBe("20.00");
    expect(result.summary.by_asset_type.map((s) => s.label)).toEqual(["MF"]);
    expect(result.summary.by_asset_type[0].weight_pct).toBe("100.00");
  });

  it("never subtracts more than the bucket the source counted", () => {
    const thin = {
      ...SUMMARY,
      net_worth: "120100.00",
      current_value: "120100.00",
      invested_total: "105000.00",
      by_asset_type: [SUMMARY.by_asset_type[0], slice("FD", "100.00", "5000.00", "0.08")],
    };
    const result = applyExclusions(thin, [FD_A, FD_B, FUND], [
      exclusion("FD:A"),
      exclusion("FD:B"),
    ]);
    expect(result.summary.net_worth).toBe("120000.00");
    expect(result.summary.invested_total).toBe("100000.00");
  });

  it("counts an exclusion whose row is not in hand as pending, and subtracts nothing", () => {
    const result = applyExclusions(SUMMARY, [FUND], [exclusion("FD:A")]);
    expect(result.summary).toBe(SUMMARY);
    expect(result.pending).toBe(1);
  });
});

describe("StatCards with exclusions", () => {
  it("states the adjusted figures and names what came off", () => {
    const excluded = applyExclusions(SUMMARY, [FD_A, FD_B, FUND], [
      exclusion("FD:A"),
      exclusion("FD:B"),
    ]);
    render(
      <StatCards summary={SUMMARY} holdingsCount={3} countIsPartial={false} excluded={excluded} />,
    );
    expect(screen.getAllByText("₹1,20,000").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/excl\. ₹333 in 2 excluded holdings/).length).toBe(2);
    expect(screen.getByText(/source reports ₹1,20,333/)).toBeTruthy();
    expect(screen.getByText("+₹20,000")).toBeTruthy();
  });
});

describe("HoldingsTable exclusion controls", () => {
  it("offers the action inline on a caveat row and badges an excluded one", () => {
    const toggled: string[] = [];
    render(
      <HoldingsTable
        rows={[FD_A, FD_B, FUND]}
        excludedKeys={new Set([`ind_money\u0000FD:B`])}
        onToggleExclude={(row) => toggled.push(row.external_id)}
      />,
    );
    expect(screen.getByText("Excluded")).toBeTruthy();
    // FD_A offers exclusion, FD_B offers restoring it, the clean fund offers neither.
    screen.getByText("Exclude from totals").click();
    screen.getByText("Include in totals").click();
    expect(toggled).toEqual(["FD:A", "FD:B"]);
  });

  it("renders no controls without the handler (the public /demo)", () => {
    render(<HoldingsTable rows={[FD_A, FUND]} />);
    expect(screen.queryByText("Exclude from totals")).toBeNull();
  });
});
