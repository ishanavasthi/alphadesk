/**
 * Card U1's landing routing table, as tests.
 *
 * `/` (`app/(marketing)/page.tsx`) renders the marketing hero flag-off; flag-on
 * it wraps `ClerkLanding`, which resolves the three signed-in states from the
 * plan's route table. This pins that decision without a live Clerk instance —
 * `@clerk/nextjs`, `useIndMoney` and `next/navigation` are mocked, which is the
 * same approach F2 took (the thing worth asserting is the branch chosen, and a
 * mock answers it exactly).
 *
 * | Clerk `isSignedIn` | IND Money `authed` | `/` renders |
 * | --- | --- | --- |
 * | false | — | the hero (children) |
 * | true | true | redirect → `/portfolio` |
 * | true | false | the Connect gate |
 * | not loaded | — | the hero (stable default, no gate flash) |
 */

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClerkLanding } from "@/components/clerk/ClerkLanding";

let user = { isLoaded: true, isSignedIn: false as boolean };
let indMoney = { authed: null as boolean | null };
const replace = vi.fn();

vi.mock("@clerk/nextjs", () => ({
  useUser: () => user,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("@/components/AuthProvider", () => ({
  useIndMoney: () => indMoney,
}));

afterEach(() => {
  replace.mockClear();
  user = { isLoaded: true, isSignedIn: false };
  indMoney = { authed: null };
});

const hero = <div data-testid="hero">marketing hero</div>;

describe("the landing routing (ClerkLanding)", () => {
  it("signed out → the marketing hero, no redirect", () => {
    user = { isLoaded: true, isSignedIn: false };
    render(<ClerkLanding>{hero}</ClerkLanding>);
    expect(screen.getByTestId("hero")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("Clerk still loading → the hero (no gate flash)", () => {
    user = { isLoaded: false, isSignedIn: false };
    render(<ClerkLanding>{hero}</ClerkLanding>);
    expect(screen.getByTestId("hero")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("signed in + linked → redirect to /portfolio", () => {
    user = { isLoaded: true, isSignedIn: true };
    indMoney = { authed: true };
    render(<ClerkLanding>{hero}</ClerkLanding>);
    expect(replace).toHaveBeenCalledWith("/portfolio");
    expect(screen.queryByTestId("hero")).toBeNull();
  });

  it("signed in + not linked → the Connect gate, no redirect", () => {
    user = { isLoaded: true, isSignedIn: true };
    indMoney = { authed: false };
    render(<ClerkLanding>{hero}</ClerkLanding>);
    expect(screen.getByText(/Link your IND Money account/i)).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
    expect(screen.queryByTestId("hero")).toBeNull();
  });

  it("signed in, link state unknown → neither hero nor gate yet", () => {
    user = { isLoaded: true, isSignedIn: true };
    indMoney = { authed: null };
    render(<ClerkLanding>{hero}</ClerkLanding>);
    expect(screen.queryByTestId("hero")).toBeNull();
    expect(screen.queryByText(/Link your IND Money account/i)).toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });
});
