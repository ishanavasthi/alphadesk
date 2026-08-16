import { SectionHead } from "./primitives";

const STEPS = [
  {
    no: "01",
    title: "Join the waitlist",
    body: "AlphaDesk is a public URL, gated by a waitlist. Register interest and you are approved in batches. No open sign-up at launch.",
  },
  {
    no: "02",
    title: "Sign in",
    body: "A normal account sign-in. Your platform identity stays separate from your broker credential; linking comes later, and only with consent.",
  },
  {
    no: "03",
    title: "Read the consent screen",
    gate: true,
    body: "Before any broker redirect, one screen names exactly what will be read, why, where it is stored, and how to delete it. Not a checkbox buried in sign-up.",
  },
  {
    no: "04",
    title: "Link IND Money, read-only",
    body: "A standard OAuth link that can only read. Tokens are encrypted at rest and never reach your browser; unlinking revokes access upstream, not just locally.",
  },
  {
    no: "05",
    title: "Dashboard, then nightly snapshots",
    body: "Your net worth, allocation and holdings render immediately. Every night at ~23:45 IST a snapshot records net worth at market close, building the daily history and trend.",
  },
];

export function HowItWorks() {
  return (
    <section id="how" aria-labelledby="how-h" className="py-14 sm:py-[72px]">
      <SectionHead
        id="how-h"
        kicker="How it works"
        title="Five steps. One consent."
        sub="From waitlist to a nightly-verified net worth."
      />
      <div className="grid max-w-[760px] gap-3 tabular-nums">
        {STEPS.map((step) => (
          <div
            key={step.no}
            className={`grid grid-cols-[40px_1fr] items-start gap-3 rounded-lg border p-4 shadow-[0_1px_2px_var(--adp-shadow)] sm:grid-cols-[56px_1fr] sm:gap-5 sm:px-6 sm:py-5 ${
              step.gate
                ? "border-[var(--adp-warn-bd)] bg-[var(--adp-warn-bg)]"
                : "border-border bg-card"
            }`}
          >
            <span
              className={`pt-0.5 text-[13px] font-semibold tracking-[0.04em] ${
                step.gate ? "text-[var(--adp-warn-ink)]" : "text-[var(--adp-faint)]"
              }`}
            >
              {step.no}
            </span>
            <div>
              <h3 className="mb-1 flex flex-wrap items-center gap-2 text-[15px] font-semibold">
                {step.title}
                {step.gate ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--adp-warn-bd)] bg-card px-2.5 py-0.5 text-[11px] font-semibold text-[var(--adp-warn-ink)]">
                    <span aria-hidden>⏸</span> unskippable by design
                  </span>
                ) : null}
              </h3>
              <p
                className={`text-[13.5px] ${
                  step.gate ? "text-[var(--adp-warn-ink)]" : "text-muted-foreground"
                }`}
              >
                {step.body}
              </p>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-5 max-w-[760px] border-l-2 border-border pl-3.5 text-[12.5px] text-muted-foreground">
        No cross-source auto-merge: holdings are grouped by instrument for display, and AlphaDesk
        asks before combining across sources. A silently wrong net worth is the one error a user
        cannot catch.
      </p>
    </section>
  );
}
