/**
 * Manual fixed deposits (card B10).
 *
 * The card's claim is narrow and worth pinning precisely: **these numbers are
 * yours, not IND Money's, and they are the server's accrual rather than this
 * app's arithmetic.** So the tests below check the places that claim could
 * quietly stop being true:
 *
 * 1. **Provenance goes missing.** The caption is the only thing separating a
 *    figure the broker vouches for from one the reader typed. It must be on
 *    screen in every state, including the empty one.
 * 2. **A matured deposit keeps accruing.** The backend freezes the value at
 *    maturity; the row has to *say* it is matured, otherwise a frozen figure
 *    looks like a stalled one.
 * 3. **A bad write reaches the API.** The client-side rules mirror the server's
 *    so the answer is instant — if a principal of 0 or a 60% rate got as far as
 *    a request, the mirror has drifted.
 * 4. **A write lands and the list is not re-read.** Nothing here patches a row
 *    in place: an edited rate changes an accrual only the backend recomputes, so
 *    every write must be followed by the provider's refresh.
 * 5. **A rupee figure surviving the privacy toggle.** Rates and dates are terms,
 *    not balances, and stay — every ₹ amount masks with the rest of the surface.
 *
 * The API is mocked with the wire shapes from issue #68; nothing talks to a
 * backend, and the card is rendered in its unconnected form because the provider
 * walks the whole source just to exist.
 */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { createFd, updateFd, deleteFd } = vi.hoisted(() => ({
  createFd: vi.fn(),
  updateFd: vi.fn(),
  deleteFd: vi.fn(),
}));

// Only the three writes are stubbed: the card reads nothing itself (the
// provider owns the list), and leaving the rest of the module real keeps the
// types and the `PortfolioError` shape honest.
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, createFd, updateFd, deleteFd };
});

import { ManualFdsCard, formatDay, validateFd } from "@/components/portfolio/ManualFds";
import { StatCards } from "@/components/portfolio/StatCards";
import { resetPrivacy, toggleAmountsHidden } from "@/components/portfolio/privacy";
import type { ManualFd } from "@/lib/api";

const fd = (over: Partial<ManualFd> = {}): ManualFd => ({
  id: "fd-1",
  label: "SBI 5-year FD",
  principal: "500000.00",
  rate_pct: "7.1000",
  compounding: "quarterly",
  start_date: "2024-03-14",
  maturity_date: "2029-03-14",
  current_value: "587412.00",
  accrued_interest: "87412.00",
  maturity_value: "711234.00",
  matured: false,
  days_to_maturity: 935,
  created_at: "2026-08-21T10:00:00+00:00",
  updated_at: "2026-08-21T10:00:00+00:00",
  ...over,
});

const MATURED = fd({
  id: "fd-2",
  label: "HDFC 1-year FD",
  principal: "100000.00",
  rate_pct: "6.5000",
  compounding: "simple",
  start_date: "2024-01-01",
  maturity_date: "2025-01-01",
  current_value: "106500.00",
  accrued_interest: "6500.00",
  maturity_value: "106500.00",
  matured: true,
  days_to_maturity: 0,
});

const DRAFT = {
  label: "Canara 2-year FD",
  principal: "250000",
  rate_pct: "7.25",
  compounding: "quarterly" as const,
  start_date: "2026-08-21",
  maturity_date: "2028-08-21",
};

/** Fill the add form with a valid deposit. */
function fillForm(over: Partial<typeof DRAFT> = {}) {
  const values = { ...DRAFT, ...over };
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: values.label } });
  fireEvent.change(screen.getByLabelText("Principal (₹)"), {
    target: { value: values.principal },
  });
  fireEvent.change(screen.getByLabelText("Rate (% a year)"), {
    target: { value: values.rate_pct },
  });
  fireEvent.change(screen.getByLabelText("Deposited on"), {
    target: { value: values.start_date },
  });
  fireEvent.change(screen.getByLabelText("Matures on"), {
    target: { value: values.maturity_date },
  });
}

function card(over: Partial<Parameters<typeof ManualFdsCard>[0]> = {}) {
  const onChanged = vi.fn(async () => {});
  const view = render(
    <ManualFdsCard
      fds={[fd()]}
      loading={false}
      note={null}
      error={null}
      onChanged={onChanged}
      {...over}
    />,
  );
  return { ...view, onChanged };
}

beforeEach(() => resetPrivacy());
afterEach(() => {
  cleanup();
  resetPrivacy();
  vi.clearAllMocks();
});

describe("the list of deposits", () => {
  it("states every term, the accrual, and where the numbers come from", () => {
    card({ fds: [fd(), MATURED] });

    // Provenance, in the header, unconditionally.
    expect(screen.getByText(/not read from IND Money/)).toBeTruthy();

    // The terms the reader typed…
    expect(screen.getByText("SBI 5-year FD")).toBeTruthy();
    expect(screen.getByText(/₹5,00,000 · 7\.10% · Quarterly · matures 14 Mar 2029/)).toBeTruthy();
    expect(screen.getByText(/in 935 days/)).toBeTruthy();
    // …and what the server accrued them to.
    expect(screen.getByText("₹5,87,412")).toBeTruthy();
    expect(screen.getByText("+₹87,412 interest")).toBeTruthy();

    // The card's own total is the sum of the rows in hand, labelled as an
    // addition to the net worth rather than a portfolio figure.
    expect(screen.getByText(/2 deposits tracked here, added to your net worth/)).toBeTruthy();
    expect(screen.getByText("₹6,93,912")).toBeTruthy();
  });

  it("marks a matured deposit and says its value is frozen", () => {
    card({ fds: [MATURED] });
    expect(screen.getByText("Matured")).toBeTruthy();
    expect(screen.getByText(/matured 1 Jan 2025 — value frozen/)).toBeTruthy();
  });

  it("invites the first deposit instead of implying there are none to have", () => {
    card({ fds: [] });
    expect(screen.getByText(/No manual deposits yet/)).toBeTruthy();
    expect(screen.getByText(/computed from its terms, not quoted by a market/)).toBeTruthy();
    // Still the header caption, with no rows on screen at all.
    expect(screen.getByText(/not read from IND Money/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add FD" }).hasAttribute("disabled")).toBe(false);
  });

  it("repeats the backend's note and refuses to take a write it cannot store", () => {
    card({ fds: [], note: "No database is configured, so nothing can be saved." });
    expect(screen.getByText(/No database is configured/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add FD" }).hasAttribute("disabled")).toBe(true);
  });

  it("surfaces a failed read rather than an empty list", () => {
    card({ fds: [], error: "Cannot reach AlphaDesk API at http://127.0.0.1:8000." });
    expect(screen.getByText(/Cannot reach AlphaDesk API/)).toBeTruthy();
    expect(screen.queryByText(/No manual deposits yet/)).toBeNull();
  });
});

describe("adding a deposit", () => {
  it("answers a bad principal, rate or date pair without calling the API", () => {
    card({ fds: [] });
    fireEvent.click(screen.getByRole("button", { name: "Add FD" }));

    // Nothing filled in at all.
    fireEvent.click(screen.getByRole("button", { name: "Add deposit" }));
    expect(screen.getByText("Give this deposit a name.")).toBeTruthy();
    expect(screen.getByText("Enter the deposited amount.")).toBeTruthy();
    expect(createFd).not.toHaveBeenCalled();

    // A zero principal, a rate past the guard, and maturity before the deposit.
    fillForm({ principal: "0", rate_pct: "60", maturity_date: "2026-01-01" });
    fireEvent.click(screen.getByRole("button", { name: "Add deposit" }));
    expect(screen.getByText("The principal must be more than ₹0.")).toBeTruthy();
    expect(screen.getByText("The rate must be 50% or less.")).toBeTruthy();
    expect(screen.getByText("Maturity must be after the deposit date.")).toBeTruthy();
    expect(createFd).not.toHaveBeenCalled();
  });

  it("sends the terms and re-reads the list rather than patching one in", async () => {
    createFd.mockResolvedValue(fd({ id: "fd-3" }));
    const { onChanged } = card({ fds: [] });

    fireEvent.click(screen.getByRole("button", { name: "Add FD" }));
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Add deposit" }));

    await waitFor(() => expect(createFd).toHaveBeenCalledTimes(1));
    expect(createFd.mock.calls[0][0]).toEqual({
      label: "Canara 2-year FD",
      principal: "250000",
      rate_pct: "7.25",
      compounding: "quarterly",
      start_date: "2026-08-21",
      maturity_date: "2028-08-21",
    });
    // The refresh is the only thing that puts a row on screen — the accrual is
    // the server's to compute.
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("keeps the dialog open and shows the server's refusal", async () => {
    createFd.mockRejectedValue(
      Object.assign(new Error("No database is configured."), { code: "no_database" }),
    );
    const { onChanged } = card({ fds: [] });

    fireEvent.click(screen.getByRole("button", { name: "Add FD" }));
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Add deposit" }));

    await screen.findByText("No database is configured.");
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Add deposit" })).toBeTruthy();
  });
});

describe("editing and removing", () => {
  it("opens on the stored terms and patches only that deposit", async () => {
    updateFd.mockResolvedValue(fd({ rate_pct: "7.5000" }));
    const { onChanged } = card();

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("SBI 5-year FD");
    expect((screen.getByLabelText("Rate (% a year)") as HTMLInputElement).value).toBe("7.1000");

    fireEvent.change(screen.getByLabelText("Rate (% a year)"), { target: { value: "7.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateFd).toHaveBeenCalledTimes(1));
    expect(updateFd.mock.calls[0][0]).toBe("fd-1");
    expect(updateFd.mock.calls[0][1]).toMatchObject({ rate_pct: "7.5", label: "SBI 5-year FD" });
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("asks before removing, and names what it is about to remove", async () => {
    deleteFd.mockResolvedValue(undefined);
    const { onChanged } = card();

    // Held onto: while the dialog is open Radix hides the rest of the card from
    // the accessibility tree, so the row's button is not queryable again.
    const rowRemove = screen.getByRole("button", { name: "Remove SBI 5-year FD" });
    fireEvent.click(rowRemove);
    expect(screen.getByText(/Remove “SBI 5-year FD”\?/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(deleteFd).not.toHaveBeenCalled();

    fireEvent.click(rowRemove);
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(deleteFd).toHaveBeenCalledWith("fd-1"));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });
});

describe("the privacy toggle", () => {
  it("masks every rupee figure and keeps the terms that are not balances", () => {
    card({ fds: [fd()] });
    // The row's accrued value, and the card's total of one row.
    expect(screen.getAllByText("₹5,87,412").length).toBe(2);

    act(() => toggleAmountsHidden());

    expect(screen.queryByText("₹5,87,412")).toBeNull();
    expect(screen.queryByText(/₹5,00,000/)).toBeNull();
    expect(screen.getByText("+₹•••••• interest")).toBeTruthy();
    // A rate and a maturity date are terms of the contract, not the balance.
    expect(screen.getByText(/7\.10% · Quarterly/)).toBeTruthy();
    expect(screen.getByText("SBI 5-year FD")).toBeTruthy();
  });
});

describe("the net-worth stat", () => {
  const summary = {
    user_id: "local",
    source: "ind_money",
    as_of: "2026-08-21T09:30:00+00:00",
    currency: "INR",
    net_worth: "1000000.00",
    current_value: "1000000.00",
    invested_total: null,
    liabilities_total: "0.00",
    pnl: null,
    pnl_pct: null,
    by_asset_type: [],
    by_asset_class: [],
    by_sector: [],
    by_market_cap: [],
    link_health: "linked" as const,
    last_captured_at: null,
  };

  it("adds the manual deposits, says so, and keeps the source's own figure", () => {
    render(
      <StatCards
        summary={summary}
        holdingsCount={3}
        countIsPartial={false}
        manual={{ total: 587412, count: 1 }}
      />,
    );

    expect(screen.getByText("₹15,87,412")).toBeTruthy();
    expect(screen.getByText(/incl\. ₹5,87,412 in 1 manual FD/)).toBeTruthy();
    expect(screen.getByText(/source reports ₹10,00,000/)).toBeTruthy();
  });

  it("is untouched when there is nothing manual to add", () => {
    render(<StatCards summary={summary} holdingsCount={3} countIsPartial={false} />);
    // Net worth and current value are the same figure in this fixture.
    expect(screen.getAllByText("₹10,00,000").length).toBe(2);
    expect(screen.queryByText(/manual FD/)).toBeNull();
  });
});

describe("the pure helpers", () => {
  it("mirrors the API's limits", () => {
    expect(validateFd({ ...DRAFT })).toEqual({});
    expect(validateFd({ ...DRAFT, label: "x".repeat(121) }).label).toBeTruthy();
    expect(validateFd({ ...DRAFT, principal: "-5" }).principal).toBeTruthy();
    expect(validateFd({ ...DRAFT, rate_pct: "50" })).toEqual({});
    expect(validateFd({ ...DRAFT, rate_pct: "50.1" }).rate_pct).toBeTruthy();
    expect(validateFd({ ...DRAFT, rate_pct: "0" }).rate_pct).toBeTruthy();
    expect(
      validateFd({ ...DRAFT, start_date: "2028-08-21", maturity_date: "2028-08-21" })
        .maturity_date,
    ).toBeTruthy();
  });

  it("renders a date without going through a timezone", () => {
    expect(formatDay("2029-03-14")).toBe("14 Mar 2029");
    expect(formatDay("")).toBe("");
  });
});
