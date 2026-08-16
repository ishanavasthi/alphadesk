import type { ReactNode } from "react";

import { Badge } from "@/components/portfolio/ui";

/**
 * The shared frame for the `/privacy` and `/terms` placeholder pages (card U1).
 *
 * These exist now so the footer's Privacy/Terms links — which D1, A1 and the
 * demo already render on every page — resolve to a real page (200) instead of a
 * 404. **The full policy is card L1's work**; a `soon` badge and a one-line note
 * say so rather than presenting a stub as the finished document. A product that
 * asks for account access owes the reader reachable links here even before the
 * text is final.
 */
export function LegalPage({
  title,
  summary,
  children,
}: {
  title: string;
  summary: string;
  children?: ReactNode;
}) {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
      <div className="mb-3 flex items-center gap-2.5">
        <h1 className="text-xl font-semibold tracking-[-0.02em]">{title}</h1>
        <Badge variant="soon">L1 · full policy at launch</Badge>
      </div>
      <p className="text-[14px] leading-relaxed text-muted-foreground">{summary}</p>
      {children ? (
        <div className="mt-6 space-y-3 text-[13.5px] leading-relaxed text-muted-foreground">
          {children}
        </div>
      ) : null}
      <p className="mt-8 text-xs text-[var(--adp-faint)]">
        This is a placeholder. The complete policy is published at launch. Questions
        in the meantime: open an issue on the project&rsquo;s GitHub.
      </p>
    </main>
  );
}
