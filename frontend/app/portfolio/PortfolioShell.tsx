"use client";

import type { ReactNode } from "react";

import { AppNav } from "@/components/shell/AppNav";
import { PortfolioTopBar } from "@/components/portfolio/PortfolioTopBar";
import { usePortfolio } from "@/components/portfolio/PortfolioProvider";

/** The dashboard's own pages, in the order they are offered. */
const PAGE_LINKS = [
  { href: "/portfolio", label: "Overview", exact: true },
  { href: "/portfolio/holdings", label: "Holdings" },
  { href: "/portfolio/performance", label: "Performance" },
];

/**
 * The chrome every `/portfolio` page shares.
 *
 * A client component only because the top bar's actions are the provider's:
 * Refresh, its cooldown and Capture all act on state that lives one level up and
 * outlives the page under it. Sitting in the layout, this renders once and stays
 * mounted while the tabs change beneath it — the page swaps, the load does not.
 */
export function PortfolioShell({ children }: { children: ReactNode }) {
  const {
    summary,
    demo,
    refresh,
    loadingHoldings,
    cooldown,
    capture,
    captureState,
  } = usePortfolio();

  return (
    <>
      <PortfolioTopBar
        linkHealth={summary.link_health}
        demo={demo}
        onRefresh={refresh}
        refreshing={loadingHoldings}
        cooldown={cooldown}
        onCapture={() => void capture()}
        captureState={captureState}
      />

      {/* The surface's own tabs, below the product-level nav in the bar above:
          one dashboard, three views of it. */}
      <AppNav links={PAGE_LINKS} className="mb-5 text-[13px]" />

      {children}
    </>
  );
}
