import type { ReactNode } from "react";

import { AuthProvider } from "@/components/AuthProvider";
import { TopBar } from "@/components/TopBar";

/**
 * The Lab — the multi-agent research desk, a labelled *simulation*.
 *
 * Every view under `/lab` (the query desk and each `/lab/a/[id]` analysis)
 * carries the banner below, unconditionally. The Lab runs live agents over real
 * NSE data but places no orders and gives no advice: its output is a paper
 * watchlist, not a portfolio. The label is a persistent part of the surface, not
 * a one-time toast, because a run that produces buy/avoid calls with confidence
 * scores reads like advice unless something on the page says otherwise on every
 * view. Kept in the layout so no page can render without it.
 *
 * **The terminal `TopBar` lives here now.** Card U1 retired the app-wide
 * `TerminalChrome` conditional; the Lab is the surface that keeps the dark
 * Bloomberg chrome, so it renders it in its own layout. `/`, `/demo` and the
 * marketing group get the light shadcn `SiteHeader`; `/portfolio` its own bar.
 */
export default function LabLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <TopBar />
      <div
        data-lab-label
        role="note"
        className="border-b border-border bg-secondary/30 px-4 py-1.5 text-center font-mono text-[0.68rem] uppercase tracking-[0.12em] text-muted-foreground sm:px-6"
      >
        Lab — a live simulation. Runs aren&rsquo;t saved. Not investment advice; no orders are placed.
      </div>
      {children}
    </AuthProvider>
  );
}
