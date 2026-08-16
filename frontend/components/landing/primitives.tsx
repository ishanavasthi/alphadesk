import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Shared bits of the "Zinc Prospectus" landing (`docs/design/landing/c-prospectus.html`).
 *
 * Everything here resolves through the DECISION token set on the `[data-adp]`
 * wrapper, so each piece inverts with the dashboard's dark variant without a
 * single theme conditional.
 */

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** Rupee amount, en-IN grouped, no decimals (DECISION conventions). */
export function inr(value: number): string {
  return `₹${INR.format(value)}`;
}

/** The rounded accent tile every feature and trust item is introduced by. */
export function IconTile({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid h-[34px] w-[34px] flex-none place-items-center rounded-lg bg-[var(--adp-accent-soft)] text-[var(--adp-accent)]",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Inline pill carrying an exact figure inside narrative prose. */
export function MetricChip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-block rounded-full border border-[var(--adp-accent-ring)] bg-[var(--adp-accent-soft)] px-2 text-[11.5px] font-medium tabular-nums text-[var(--adp-chip-ink)]">
      {children}
    </span>
  );
}

/** Small outlined pill used for agent and pipeline stages. */
export function StageChip({
  children,
  tone,
}: {
  children: ReactNode;
  tone?: "warn";
}) {
  return (
    <span
      className={cn(
        "whitespace-nowrap rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground",
        tone === "warn" &&
          "border-[var(--adp-warn-bd)] bg-[var(--adp-warn-bg)] text-[var(--adp-warn-ink)]",
      )}
    >
      {children}
    </span>
  );
}

/** The arrow separating two stage chips. */
export function StageArrow() {
  return (
    <span aria-hidden className="self-center text-[11px] text-[var(--adp-faint)]">
      &rarr;
    </span>
  );
}

/** Section kicker, title and subtitle, at the locked type scale. */
export function SectionHead({
  kicker,
  title,
  sub,
  id,
}: {
  kicker: string;
  title: ReactNode;
  sub: ReactNode;
  id: string;
}) {
  return (
    <div className="mb-10 max-w-[560px]">
      <div className="mb-2.5 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--adp-accent)]">
        {kicker}
      </div>
      <h2 id={id} className="mb-2.5 text-[28px] font-semibold leading-tight tracking-[-0.02em]">
        {title}
      </h2>
      <p className="text-[15px] text-muted-foreground">{sub}</p>
    </div>
  );
}

/** Bento card: half the six-column grid on desktop, stacked below. */
export function BentoCard({ children }: { children: ReactNode }) {
  return (
    <div className="col-span-1 flex min-w-0 flex-col gap-2.5 rounded-lg border border-border bg-card p-6 shadow-[0_1px_2px_var(--adp-shadow)] sm:col-span-3">
      {children}
    </div>
  );
}
