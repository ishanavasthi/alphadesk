import Link from "next/link";
import { Github } from "lucide-react";

import { AUTH_ENABLED } from "@/lib/auth";
import { ThemeToggle } from "@/components/portfolio/ThemeToggle";

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
 * more: each surface declares its own chrome. This replaces the interim
 * `TerminalChrome` component D1 left for U1 to retire.
 *
 * The identity slot is flag-gated (`SiteAuthSlot`): flag off it renders nothing
 * and ships no Clerk; flag on it shows sign-in / the account avatar.
 *
 * `ThemeToggle` is the dashboard's own component, mounted here unchanged: it
 * flips `data-adp-theme` on the `#adp-root` wrapper the marketing layout
 * declares and stores the choice under `adp-theme`, so light and dark are one
 * mechanism and one stored choice across the whole product.
 */
export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-3 px-4 sm:gap-5 sm:px-6">
        <Link href="/" className="flex-none whitespace-nowrap font-semibold tracking-[-0.01em]">
          alpha<b className="text-[var(--adp-accent)]">Desk</b>
        </Link>
        {/* Below `sm` the row cannot hold the link cluster *and* the identity
            actions: at 360px the two together overflow, which is what pushed
            "Join waitlist" off the right edge and wrapped "Sign in" onto two
            lines. So the cluster steps aside on phones and the row keeps the
            wordmark, the theme toggle and the identity actions — the things a
            visitor has to be able to reach — on one line. Nothing is stranded:
            "Live demo" is the hero's primary CTA and is repeated in the closing
            block, and the signed-in identity control carries its own Portfolio
            link. */}
        <nav className="hidden items-center gap-3 whitespace-nowrap text-[13px] text-muted-foreground sm:flex sm:gap-4">
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
              className="text-[13px] whitespace-nowrap"
            />
          ) : null}
        </nav>
        <span className="min-w-0 flex-1" />
        {/* The row has no slack on a phone, so this icon steps aside below `sm`
            too. Nothing is lost — the footer carries the same repository link as
            "Open source" on every page. */}
        <a
          href="https://github.com/ishanavasthi/alphadesk"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Source code on GitHub"
          className="hidden flex-none text-muted-foreground transition-colors hover:text-foreground sm:block"
        >
          <Github className="h-4 w-4" />
        </a>
        <ThemeToggle />
        <SiteAuthSlot />
      </div>
    </header>
  );
}
