"use client";

import Link from "next/link";
import { AlertTriangle, Github, KeyRound, Loader2, LogOut } from "lucide-react";

import { useIndMoney } from "@/components/AuthProvider";
import { AppNav } from "@/components/shell/AppNav";
import { ThemeToggle } from "@/components/portfolio/ThemeToggle";
import { UserMenu } from "@/components/UserMenu";
import { WatchlistButton } from "@/components/lab/WatchlistButton";
import { Button, Chip } from "@/components/ui/adp";
import { AUTH_ENABLED } from "@/lib/auth";

/** The product surfaces, in the order they are offered everywhere. */
const NAV_LINKS = [
  { href: "/portfolio", label: "Portfolio" },
  { href: "/lab", label: "Lab" },
];

/**
 * The Lab's top bar — the dashboard's bar, with the Lab's own controls in it.
 *
 * Issue #18 retired the terminal chrome this replaced (`components/TopBar.tsx`,
 * uppercase mono wordmark on a near-black sticky header, plus a separate
 * `AuthButton` of amber pills). Everything here resolves through the DECISION
 * tokens, so it inverts with `data-adp-theme` exactly as `PortfolioTopBar` does
 * and no part of it knows which theme it is in.
 *
 * The IND Money control follows the dashboard's convention rather than inventing
 * a second one: when a link exists the *status chip is the disconnect button* —
 * the thing the reader is already looking at is the obvious place to press —
 * and when it doesn't, the accent button is the one call to action on the page.
 * Unlike the dashboard this disconnects directly through the provider: the Lab's
 * link is the broker session, not the account, so there is no `UnlinkDialog`
 * here.
 */
export function LabTopBar() {
  const { authed, waking, busy, error, connect, disconnect } = useIndMoney();
  const checking = authed === null;

  return (
    // min-height, not height: the actions wrap to a second row at 375px, and a
    // fixed 56px header would let them spill over the page title.
    <header className="flex min-h-14 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border py-2">
      {/* With the flag off the Lab is the whole app, so the wordmark stays put
          rather than walking to a dashboard nobody can reach. */}
      <Link
        href={AUTH_ENABLED ? "/portfolio" : "/lab"}
        className="font-semibold tracking-[-0.01em]"
      >
        alpha<b className="text-[var(--adp-accent)]">Desk</b>
      </Link>
      <AppNav links={NAV_LINKS} className="text-[13px]" />
      <span className="flex-1" />
      <ThemeToggle />
      <WatchlistButton />
      {authed ? (
        <button
          type="button"
          onClick={disconnect}
          disabled={busy}
          title="Disconnect IND Money from AlphaDesk"
          className="rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        >
          <Chip tone="ok">
            IND Money · linked
            {busy ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <LogOut className="h-3 w-3" />
            )}
          </Chip>
        </button>
      ) : (
        <Button
          variant="accent"
          size="sm"
          onClick={connect}
          disabled={busy || checking}
          title={
            waking
              ? "The backend is cold-starting — this can take up to a minute."
              : (error ?? "Authenticate the backend with IND Money.")
          }
        >
          {busy || checking ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : error ? (
            <AlertTriangle className="h-3.5 w-3.5" />
          ) : (
            <KeyRound className="h-3.5 w-3.5" />
          )}
          {waking ? "Waking backend…" : error ? "Connect failed — retry" : "Connect IND Money"}
        </Button>
      )}
      <a
        href="https://github.com/ishanavasthi/alphadesk"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Source code on GitHub"
        className="text-muted-foreground transition-colors hover:text-foreground"
      >
        <Github className="h-4 w-4" />
      </a>
      {/* "Who are you", next to "is a broker linked" — the same flag-gated Clerk
          slot the dashboard carries. Renders (and downloads) nothing flag-off. */}
      <UserMenu />
    </header>
  );
}
