import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/components/AuthProvider";
import { LabTopBar } from "@/components/lab/LabTopBar";
import { ThemeBootstrap } from "@/components/shell/ThemeBootstrap";
import { Badge, SurfaceFooter } from "@/components/ui/adp";
import "../portfolio/portfolio.css";

export const metadata: Metadata = {
  title: "Lab — AlphaDesk",
  description:
    "A multi-agent equity research simulation over live NSE data. Results reach a paper watchlist only; no orders are placed and nothing here is investment advice.",
};

/**
 * The Lab — the multi-agent research desk, a labelled *simulation*.
 *
 * ## The band
 *
 * Every view under `/lab` (the query desk and each `/lab/a/[id]` analysis)
 * carries it, unconditionally. The Lab runs live agents over real NSE data but
 * places no orders and gives no advice: its output is a paper watchlist, not a
 * portfolio. The label is a persistent part of the surface, not a one-time
 * toast, because a run that produces buy/avoid calls with confidence scores
 * reads like advice unless something on the page says otherwise on every view.
 * Kept in the layout so no page can render without it.
 *
 * ## The chrome
 *
 * Issue #18 moved the Lab onto the product theme. `data-adp` scopes the DECISION
 * token set (`../portfolio/portfolio.css`) exactly as `/portfolio`, `/demo` and
 * the marketing group do, and `ThemeBootstrap` — which owns both the pre-paint
 * inline script and the mount effect a client-side route change needs — keeps
 * `data-adp-theme` right, so Portfolio → Lab → Portfolio holds one theme
 * throughout. `id="adp-root"` is what both of those
 * and `ui/dialog`'s portal reach for. `min-h-screen` matters: the wrapper is what paints the ground.
 *
 * What used to be here — the dark Bloomberg `TopBar`, a mono uppercase band —
 * is gone. The Lab's identity is now carried by the purple `lab` badge and the
 * words beside it, which is where an identity belongs; see
 * `docs/design/DECISION.md` § "The Lab joins the direction".
 */
export default function LabLayout({ children }: { children: ReactNode }) {
  return (
    // `suppressHydrationWarning`: the bootstrap's inline script stamps
    // `data-adp-theme` here before React hydrates — that is the point of it, and
    // it is by construction an attribute the server HTML does not have. This
    // keeps the intended mismatch silent and a real one audible; it covers this
    // element only, not its children.
    <div
      id="adp-root"
      suppressHydrationWarning
      data-adp
      className="min-h-screen bg-background text-foreground"
    >
      <ThemeBootstrap />
      <AuthProvider>
        <div className="mx-auto max-w-[1120px] px-4 pb-16 sm:px-6">
          <LabTopBar />
          <div
            data-lab-label
            role="note"
            className="mt-4 flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-[var(--adp-lab-bd)] bg-[var(--adp-lab-bg)] px-3.5 py-2.5 text-[12.5px] text-[var(--adp-lab-ink)]"
          >
            <Badge variant="lab">Lab · simulation</Badge>
            <span>
              <b className="font-semibold">A live simulation.</b> Runs aren&rsquo;t saved. Not
              investment advice; no orders are placed.
            </span>
            <span className="flex-1" />
            <span className="hidden sm:inline">Paper watchlist only</span>
          </div>
          {children}
          {/* Privacy/Terms are reachable from every page's footer (card L1). */}
          <SurfaceFooter note="Runs are simulations and aren’t saved" />
        </div>
      </AuthProvider>
    </div>
  );
}
