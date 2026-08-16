import Link from "next/link";

/**
 * The public landing hero (`docs/design/a4-shell.html`, "Public landing").
 *
 * What it is, and one CTA to the demo. The "Join the waitlist" CTA only appears
 * with the flag on — `/waitlist` is a Clerk route that 404s until L1 turns
 * sign-in on (F2), so linking to it in the flag-off build would be a knowingly
 * broken link. Flag off, the live demo is the single public entry point, which
 * is exactly the shipped state.
 */
export function LandingHero({ authEnabled }: { authEnabled: boolean }) {
  return (
    <main className="mx-auto max-w-[1120px] px-4 sm:px-6">
      <section className="mx-auto max-w-2xl py-20 text-center sm:py-28">
        <p className="mb-4 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--adp-faint)]">
          Indian-equity research desk
        </p>
        <h1 className="text-[32px] font-bold leading-[1.1] tracking-[-0.03em] sm:text-[44px]">
          Your whole portfolio,
          <br />
          one honest dashboard.
        </h1>
        <p className="mx-auto mt-5 max-w-md text-[15px] leading-relaxed text-muted-foreground">
          Link your IND Money account and see net worth, allocation and history —
          computed, verified, and narrated. Nothing here is investment advice.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/demo"
            className="rounded-md bg-[var(--adp-accent)] px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-[#1d4ed8]"
          >
            Try the live demo
          </Link>
          {authEnabled ? (
            <Link
              href="/waitlist"
              className="rounded-md border border-border bg-card px-4 py-2 text-[13px] font-medium text-foreground transition-colors hover:bg-secondary"
            >
              Join the waitlist
            </Link>
          ) : null}
        </div>
      </section>

      <section className="mx-auto grid max-w-3xl gap-4 pb-16 sm:grid-cols-3">
        {[
          {
            title: "Computed, not guessed",
            body: "Every figure is derived in Python from a source call. A missing cost basis renders “—”, never a fabricated return.",
          },
          {
            title: "Narrated by agents",
            body: "A multi-agent overview describes allocation and concentration in plain language — and cites only numbers it was given.",
          },
          {
            title: "Read-only, no orders",
            body: "Access is read-only and revocable. The research desk is a paper simulation; the broker layer cannot place a trade.",
          },
        ].map((f) => (
          <div
            key={f.title}
            className="rounded-lg border border-border bg-card p-5 text-left shadow-[0_1px_2px_rgba(0,0,0,.04)]"
          >
            <h2 className="text-sm font-semibold">{f.title}</h2>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{f.body}</p>
          </div>
        ))}
      </section>
    </main>
  );
}
