import Link from "next/link";

/**
 * The unmissable, persistent sample-data banner for `/demo`
 * (`docs/design/a4-shell.html`, "Demo mode").
 *
 * `sticky top-0` is load-bearing, not decoration: a screenshot of a fake net
 * worth with no context is genuinely misleading, so the disclaimer has to be on
 * screen at **every** scroll position, not just at the top of the page. The
 * amber treatment is the locked warn-banner palette (DECISION.md).
 *
 * The CTA points at `/` rather than `/waitlist` because the waitlist is a Clerk
 * route that 404s until L1 (F2); the landing is the entry point that always
 * resolves and carries the waitlist CTA itself when it is live.
 */
export function DemoBanner() {
  return (
    <div className="sticky top-0 z-50 border-b border-[var(--adp-warn-bd)] bg-[var(--adp-warn-bg)] text-[var(--adp-warn-ink)]">
      <div className="mx-auto flex max-w-[1120px] flex-wrap items-center gap-x-2 gap-y-1 px-4 py-2 text-[12.5px] font-medium sm:px-6">
        <span aria-hidden>▲</span>
        <span>
          Sample data — this is a demonstration with invented holdings. Nothing on
          this page is real.
        </span>
        <span className="flex-1" />
        <Link href="/" className="whitespace-nowrap font-semibold underline underline-offset-2">
          Get your own dashboard →
        </Link>
      </div>
    </div>
  );
}
