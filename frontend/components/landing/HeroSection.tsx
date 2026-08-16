import Link from "next/link";
import { ArrowRight, Info, Lock, ShieldCheck, UserRound } from "lucide-react";

import { DashboardMock } from "./DashboardMock";

const TRUST_BADGES = [
  { icon: Lock, label: "Read-only broker access" },
  { icon: Info, label: "Descriptive, never advisory" },
  { icon: ShieldCheck, label: "Tokens encrypted at rest" },
  { icon: UserRound, label: "Delete-my-data built in" },
];

/**
 * The hero: what AlphaDesk is, the two CTAs, the trust badges, and the
 * miniature dashboard beside them.
 *
 * `authEnabled` gates the waitlist CTA exactly as it always has. `/waitlist` is
 * a Clerk route that 404s with the flag off, so linking to it in that build
 * would be a knowingly broken link.
 */
export function HeroSection({ authEnabled }: { authEnabled: boolean }) {
  return (
    <section aria-labelledby="hero-h" className="py-12 sm:py-16 lg:py-[72px]">
      <div className="grid items-center gap-11 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-14">
        <div>
          <span className="mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--adp-accent)]" aria-hidden />
            Portfolio analyzer · IND Money · waitlist
          </span>
          <h1
            id="hero-h"
            className="mb-[18px] text-[31px] font-semibold leading-[1.12] tracking-[-0.025em] sm:text-4xl lg:text-[44px]"
          >
            Your whole net worth.
            <br />
            <span className="text-muted-foreground">Verified, then narrated.</span>
          </h1>
          <p className="mb-7 max-w-[46ch] text-base text-muted-foreground sm:text-[16.5px]">
            AlphaDesk links your IND Money account read-only and shows your net worth,
            allocation, holdings and daily history, with an AI overview that narrates numbers
            computed in Python. It never invents a figure, and it never places an order.
          </p>
          <div className="mb-6 flex flex-wrap gap-3">
            <Link
              href="/demo"
              className="inline-flex items-center gap-[7px] rounded-md bg-[var(--adp-accent)] px-4 py-2.5 text-sm font-medium text-[var(--adp-accent-ink)] transition-colors hover:bg-[var(--adp-accent-strong)]"
            >
              View the live demo
              <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
            {authEnabled ? (
              <Link
                href="/waitlist"
                className="inline-flex items-center rounded-md border border-border bg-card px-4 py-2.5 text-sm font-medium transition-colors hover:bg-secondary"
              >
                Join the waitlist
              </Link>
            ) : null}
          </div>
          <ul aria-label="Trust badges" className="flex flex-wrap gap-2">
            {TRUST_BADGES.map(({ icon: Icon, label }) => (
              <li
                key={label}
                className="inline-flex items-center gap-[7px] rounded-full border border-border bg-card px-3 py-1 text-[12.5px] text-muted-foreground"
              >
                <Icon className="h-3 w-3 flex-none text-[var(--adp-accent)]" aria-hidden />
                {label}
              </li>
            ))}
          </ul>
        </div>

        <DashboardMock />
      </div>
    </section>
  );
}
