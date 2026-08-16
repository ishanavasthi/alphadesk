"use client";

import { CapStrip } from "@/components/portfolio/CapStrip";
import { NetWorthTrend } from "@/components/portfolio/NetWorthTrend";
import { usePortfolio } from "@/components/portfolio/PortfolioProvider";
import { StalenessBanner } from "@/components/portfolio/StalenessBanner";
import { Card, CardHead, PortfolioFooter } from "@/components/portfolio/ui";

/**
 * `/portfolio/performance` — the captured history, at full width.
 *
 * The staleness banner stays directly above the line for the same reason it sits
 * above the numbers on Overview: a trend drawn from a history that stopped
 * accruing has to say so before it is read. Days missed cannot be backfilled
 * from a point-in-time source, so the gap is the truth and the line is never
 * forward-filled to hide it.
 */
export default function PortfolioPerformancePage() {
  const { summary, demo, history, lastCapturedAt } = usePortfolio();

  return (
    <>
      <StalenessBanner lastCapturedAt={lastCapturedAt} />

      <NetWorthTrend points={history} lastCapturedAt={lastCapturedAt} />

      <Card className="mt-4">
        <CardHead title="Market cap mix" desc="Equity holdings by cap band" />
        <CapStrip slices={summary.by_market_cap} />
      </Card>

      <PortfolioFooter demo={demo} />
    </>
  );
}
