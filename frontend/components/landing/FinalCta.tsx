import Link from "next/link";
import { ArrowRight } from "lucide-react";

export function FinalCta({ authEnabled }: { authEnabled: boolean }) {
  return (
    <section aria-labelledby="final-h" className="py-16 text-center sm:py-[88px]">
      <h2
        id="final-h"
        className="mb-2.5 text-[26px] font-semibold leading-tight tracking-[-0.02em] sm:text-[32px]"
      >
        Every number verified.
        <br />
        See it on sample data.
      </h2>
      <p className="mx-auto mb-7 max-w-[52ch] text-[15px] text-muted-foreground">
        Open the live demo, the full dashboard on sample data with no sign-in required, or join
        the waitlist to see your own net worth this way.
      </p>
      <div className="mb-[18px] flex flex-wrap justify-center gap-3">
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
      <p className="text-[12.5px] text-[var(--adp-faint)]">
        Sample data · read-only broker access · descriptive analytics only · not investment advice
      </p>
    </section>
  );
}
