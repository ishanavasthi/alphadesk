import Link from "next/link";
import { Github } from "lucide-react";

import { AUTH_ENABLED } from "@/lib/auth";

import { AppNav } from "./AppNav";
import { SiteAuthSlot } from "./SiteAuthSlot";

/**
 * The shadcn chrome for the product surfaces (`/`, `/demo`, and the rest of the
 * marketing group).
 *
 * Card U1 owns one clean chrome mechanism: the light shadcn header here lives on
 * the product/marketing surfaces, the dark terminal `TopBar` lives on the Lab
 * (`/lab/*`, in that segment's own layout), and `/portfolio` carries its own
 * `PortfolioTopBar`. There is no per-route conditional in the root layout any
 * more — each surface declares its own chrome. This replaces the interim
 * `TerminalChrome` component D1 left for U1 to retire.
 *
 * The identity slot is flag-gated (`SiteAuthSlot`): flag off it renders nothing
 * and ships no Clerk; flag on it shows sign-in / the account avatar.
 */
export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-5 px-4 sm:px-6">
        <Link href="/" className="font-semibold tracking-[-0.01em]">
          alpha<b className="text-[var(--adp-accent)]">Desk</b>
        </Link>
        <nav className="flex items-center gap-4 text-[13px] text-muted-foreground">
          <Link href="/demo" className="transition-colors hover:text-foreground">
            Live demo
          </Link>
          {/* The app surfaces only exist for someone who can sign in. Gated in
              JSX so a flag-off build renders no link to a page its visitors
              cannot reach. */}
          {AUTH_ENABLED ? (
            <AppNav
              links={[
                { href: "/portfolio", label: "Portfolio" },
                { href: "/lab", label: "Lab" },
              ]}
              className="text-[13px]"
            />
          ) : null}
        </nav>
        <span className="flex-1" />
        <a
          href="https://github.com/ishanavasthi/alphadesk"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Source code on GitHub"
          className="text-muted-foreground transition-colors hover:text-foreground"
        >
          <Github className="h-4 w-4" />
        </a>
        <SiteAuthSlot />
      </div>
    </header>
  );
}
