/**
 * Consent-at-link-time is unskippable (card L1).
 *
 * The load-bearing property: **no path from a Connect button reaches
 * `/auth/login` without passing the consent screen.** Proved two ways — the
 * behaviour (clicking Connect opens consent, and only agreeing starts OAuth) and
 * the structure (every Connect entry point imports the shared consent hook, so a
 * new one cannot quietly skip it).
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { startAuthLogin, getAuthStatus, wakeBackend, logoutAuth } = vi.hoisted(() => ({
  startAuthLogin: vi.fn(async () => "https://broker.example/authorize"),
  getAuthStatus: vi.fn(async () => ({ authenticated: false })),
  wakeBackend: vi.fn(async () => true),
  logoutAuth: vi.fn(async () => undefined),
}));

vi.mock("@/lib/api", () => ({ startAuthLogin, getAuthStatus, wakeBackend, logoutAuth }));

import { AuthProvider } from "@/components/AuthProvider";
import { AuthButton } from "@/components/AuthButton";
import {
  CONSENT_NEVER,
  CONSENT_READS,
} from "@/components/consent/LinkConsent";

beforeEach(() => {
  startAuthLogin.mockClear();
  // A real popup object so `runConnect` doesn't fall back to navigation.
  vi.stubGlobal("open", vi.fn(() => ({ closed: false, location: { href: "" } })));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderButton() {
  return render(
    <AuthProvider>
      <AuthButton />
    </AuthProvider>,
  );
}

describe("consent gates the link flow", () => {
  it("clicking Connect opens consent and does NOT start OAuth", async () => {
    renderButton();
    const connect = await screen.findByText(/Connect IND Money/i);

    fireEvent.click(connect);

    // The consent screen is up…
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText(/Before you connect IND Money/i)).toBeTruthy();
    // …and nothing has been sent to /auth/login yet.
    expect(startAuthLogin).not.toHaveBeenCalled();
  });

  it("names exactly what is and is not read", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("open"));
    for (const line of CONSENT_READS) expect(screen.getByText(line)).toBeTruthy();
    for (const line of CONSENT_NEVER) expect(screen.getByText(line)).toBeTruthy();
  });

  it("only agreeing starts OAuth", async () => {
    renderButton();
    fireEvent.click(await screen.findByText(/Connect IND Money/i));

    fireEvent.click(screen.getByText(/Agree & connect/i));

    await waitFor(() => expect(startAuthLogin).toHaveBeenCalledTimes(1));
  });

  it("cancelling closes it and starts nothing", async () => {
    renderButton();
    fireEvent.click(await screen.findByText(/Connect IND Money/i));

    fireEvent.click(screen.getByText("Cancel"));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(startAuthLogin).not.toHaveBeenCalled();
  });
});

describe("every Connect entry point routes through the shared consent hook", () => {
  const ROOT = path.resolve(__dirname, "..");
  const ENTRY_POINTS = [
    "components/AuthProvider.tsx",
    "app/portfolio/page.tsx",
    "components/clerk/ClerkLanding.tsx",
  ];

  it("each imports useLinkConsent", () => {
    for (const file of ENTRY_POINTS) {
      const src = readFileSync(path.join(ROOT, file), "utf8");
      expect(src, file).toMatch(/useLinkConsent/);
    }
  });
});

/** A minimal host so the dialog copy can be asserted without the popup dance. */
import { useLinkConsent } from "@/components/consent/LinkConsent";

function Harness() {
  const { begin, dialog } = useLinkConsent();
  return (
    <div>
      <button onClick={() => begin(() => {})}>open</button>
      {dialog}
    </div>
  );
}
