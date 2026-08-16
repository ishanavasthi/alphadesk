/**
 * Coming back from the IND Money OAuth round trip.
 *
 * The backend used to end the link flow on its own origin with a "you can close
 * this window" page — right for the popup it was written for, a dead end once
 * every Connect button navigates the current tab. It now redirects here with
 * `?ind=connected` or `?ind=error&reason=<code>`.
 *
 * Two things are pinned:
 *
 * 1. **The outcome is read and then erased.** Leaving `?ind=` in the address bar
 *    means a refresh — or a pasted link — replays an outcome that is no longer
 *    true, which is how a user ends up staring at "connecting failed" on a
 *    perfectly healthy link.
 * 2. **An unknown `reason` still says something.** The codes come from the
 *    backend's closed set, but a version skew between the two deploys must
 *    degrade to generic copy rather than render nothing.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

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
import { getPortfolioSummary } from "@/lib/api";

/** Land on /portfolio with the query string the callback redirected with. */
function arriveWith(query: string): void {
  window.history.replaceState(null, "", `/portfolio${query}`);
}

beforeEach(() => {
  // Not linked, so the page settles on the Connect gate — where a link failure
  // is the thing the reader needs to see.
  vi.mocked(getPortfolioSummary).mockRejectedValue(
    Object.assign(new Error("not linked"), { code: "not_linked" }),
  );
});

describe("returning from the OAuth callback", () => {
  it("shows why a failed link failed", async () => {
    arriveWith("?ind=error&reason=denied");

    render(<PortfolioPage />);

    expect(
      await screen.findByText(/You declined the IND Money authorisation/i),
    ).toBeTruthy();
  });

  it("falls back to generic copy for an unrecognised reason", async () => {
    arriveWith("?ind=error&reason=some_future_code");

    render(<PortfolioPage />);

    expect(
      await screen.findByText(/Connecting to IND Money failed/i),
    ).toBeTruthy();
  });

  it("strips the callback parameters so a refresh cannot replay them", async () => {
    arriveWith("?ind=error&reason=denied");

    render(<PortfolioPage />);

    await waitFor(() => expect(window.location.search).toBe(""));
    expect(window.location.pathname).toBe("/portfolio");
  });

  it("keeps unrelated query parameters", async () => {
    arriveWith("?ind=connected&keep=me");

    render(<PortfolioPage />);

    await waitFor(() => expect(window.location.search).toBe("?keep=me"));
  });

  it("says nothing on a successful return", async () => {
    arriveWith("?ind=connected");

    render(<PortfolioPage />);

    await waitFor(() => expect(window.location.search).toBe(""));
    expect(screen.queryByText(/failed|declined|expired/i)).toBeNull();
  });

  it("leaves an ordinary visit alone", async () => {
    arriveWith("");

    render(<PortfolioPage />);

    await waitFor(() => expect(window.location.pathname).toBe("/portfolio"));
    expect(screen.queryByText(/failed|declined|expired/i)).toBeNull();
  });
});
