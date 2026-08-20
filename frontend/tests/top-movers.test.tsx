/**
 * Top movers (card B8) — the basis split, the empty state, and the toggle.
 *
 * The card's whole claim is that a number is only shown where the data supports
 * it, so these are the three ways it could quietly stop being true:
 *
 * 1. **A balance row rendered as a mover.** A savings-account deposit is the
 *    largest rupee change in a real week (issue #66's data check) and would top
 *    any list that ranked by Δ₹. It belongs in "money moved", never in gainers.
 * 2. **An opened or closed position rendered as ±100%.** It existed at one
 *    endpoint; there is no comparison, and inventing one is the most misleading
 *    number this surface could print.
 * 3. **A rupee figure surviving the privacy toggle.** Percentages stay — that is
 *    the point of the toggle — but every ₹ amount here goes through `format.ts`
 *    and must mask with the rest of the surface.
 *
 * The API is mocked with the fixed contract from issue #66; nothing here talks
 * to a backend.
 */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ getMovers: vi.fn() }));

import { TopMovers } from "@/components/portfolio/TopMovers";
import { presetWindow } from "@/components/portfolio/TopMovers";
import { resetPrivacy, toggleAmountsHidden } from "@/components/portfolio/privacy";
import { getMovers } from "@/lib/api";

const row = (over: Record<string, unknown>) => ({
  source: "ind_money",
  external_id: "INDS00577",
  asset_type: "IND_STOCK",
  name: null,
  symbol: null,
  basis: "price",
  start_price: "100.0",
  end_price: "110.0",
  start_value: "1000.0",
  end_value: "1100.0",
  change_abs: "100.0",
  change_pct: "10.0",
  currency: "INR",
  ...over,
});

const PAYLOAD = {
  requested: { from: "2026-08-14", to: "2026-08-21" },
  compared: { from: "2026-08-16", to: "2026-08-20" },
  note: "Compared 2026-08-16 → 2026-08-20 — the captured days inside the window.",
  gainers: [
    row({ external_id: "INDS00577", name: "Tata Motors", change_abs: "2500.0", change_pct: "4.2" }),
  ],
  losers: [
    row({
      external_id: "INDS00901",
      name: null,
      change_abs: "-1800.0",
      change_pct: "-3.1",
    }),
  ],
  flows: [
    row({
      external_id: "SA-8891",
      asset_type: "SA",
      name: "HDFC Savings",
      basis: "balance",
      start_price: null,
      end_price: null,
      change_abs: "16500.0",
      change_pct: null,
    }),
  ],
  opened: [
    row({ external_id: "FD-4410", asset_type: "FD", name: "SBI FD", basis: "opened" }),
  ],
  closed: [
    row({ external_id: "INDS00112", asset_type: "IND_STOCK", name: "Wipro", basis: "closed" }),
  ],
  excluded: [{ asset_type: "MF", reason: "bucket failed on 2026-08-18" }],
};

const EMPTY = {
  requested: { from: "2026-08-14", to: "2026-08-21" },
  compared: { from: null, to: null },
  note: "History has fewer than two captured days in this window.",
  gainers: [],
  losers: [],
  flows: [],
  opened: [],
  closed: [],
  excluded: [],
};

const mocked = () => vi.mocked(getMovers);

beforeEach(() => resetPrivacy());
afterEach(() => {
  cleanup();
  resetPrivacy();
  vi.clearAllMocks();
});

describe("basis decides which list a row lands in", () => {
  it("ranks price rows, files balance rows as money moved, and never invents ±100%", async () => {
    mocked().mockResolvedValue(PAYLOAD as never);
    render(<TopMovers />);

    // Ranked rows carry both columns: the percentage is the market move, the
    // rupee figure is its size.
    expect(await screen.findByText("Tata Motors")).toBeTruthy();
    expect(screen.getByText("+4.2%")).toBeTruthy();
    expect(screen.getByText("+₹2,500")).toBeTruthy();
    expect(screen.getByText("−3.1%")).toBeTruthy();
    // No name and no symbol: the identity pair's id, not a guess.
    expect(screen.getByText("INDS00901")).toBeTruthy();

    // The savings deposit is the biggest rupee change in the payload and is
    // still not a mover — it sits under its own labelled heading, with no
    // percentage beside it.
    const flows = screen.getByText("Money moved");
    expect(flows).toBeTruthy();
    expect(screen.getByText(/not market movement/i)).toBeTruthy();
    expect(screen.getByText("HDFC Savings")).toBeTruthy();
    expect(screen.getByText("+₹16,500")).toBeTruthy();

    // Opened/closed are named, and nowhere on the card is a ±100%.
    expect(screen.getByText(/Opened:/)).toBeTruthy();
    expect(screen.getByText(/SBI FD/)).toBeTruthy();
    expect(screen.getByText(/Wipro/)).toBeTruthy();
    expect(screen.queryByText(/100\.0%/)).toBeNull();

    // The snapped window and the unknown bucket are both stated.
    // Twice: the card subtitle and the "snapped" note beneath it.
    expect(screen.getAllByText(/2026-08-16 → 2026-08-20/).length).toBe(2);
    expect(screen.getByText(/bucket failed on 2026-08-18/)).toBeTruthy();
  });

  it("changes the requested window when a preset is chosen", async () => {
    mocked().mockResolvedValue(PAYLOAD as never);
    render(<TopMovers />);
    await screen.findByText("Tata Motors");

    fireEvent.click(screen.getByText("1M"));
    await waitFor(() => expect(mocked().mock.calls.length).toBeGreaterThan(1));

    const [from, to] = mocked().mock.calls.at(-1)!;
    expect(from).toBe(presetWindow("1M", new Date()).from);
    expect(to).toBe(presetWindow("1M", new Date()).to);
  });

  it("maps YTD to January 1st of the attributed day's year", () => {
    // 2026-08-21T10:00 IST — comfortably past the 06:00 attribution cutoff.
    const window = presetWindow("YTD", new Date("2026-08-21T04:30:00Z"));
    expect(window).toEqual({ from: "2026-01-01", to: "2026-08-21" });
  });
});

describe("empty and masked states", () => {
  it("says there is nothing to compare rather than drawing an empty ranking", async () => {
    mocked().mockResolvedValue(EMPTY as never);
    render(<TopMovers />);

    expect(await screen.findByText(/Nothing to compare yet/)).toBeTruthy();
    expect(screen.getByText(/fewer than two captured days/)).toBeTruthy();
    expect(screen.queryByText("Gainers")).toBeNull();
  });

  it("masks every rupee amount and keeps every percentage", async () => {
    mocked().mockResolvedValue(PAYLOAD as never);
    render(<TopMovers />);
    expect(await screen.findByText("+₹2,500")).toBeTruthy();

    // The toggle lives outside this card (the top bar); flipping the module
    // flag is what the button does.
    act(() => toggleAmountsHidden());

    expect(screen.queryByText("+₹2,500")).toBeNull();
    expect(screen.getAllByText("+₹••••••").length).toBeGreaterThan(0);
    // The analysis survives: percentages and names are not the balance.
    expect(screen.getByText("+4.2%")).toBeTruthy();
    expect(screen.getByText("Tata Motors")).toBeTruthy();
  });
});
