"use client";

import { AiOverview } from "@/components/portfolio/AiOverview";
import { AllocationBars, AllocationBarsSkeleton } from "@/components/portfolio/AllocationBars";
import { CapStrip } from "@/components/portfolio/CapStrip";
import { NetWorthTrend } from "@/components/portfolio/NetWorthTrend";
import { usePortfolio } from "@/components/portfolio/PortfolioProvider";
import { StalenessBanner } from "@/components/portfolio/StalenessBanner";
import { StatCards } from "@/components/portfolio/StatCards";
import { typeLabel } from "@/components/portfolio/format";
import { Badge, Button, Card, CardHead, PortfolioFooter } from "@/components/portfolio/ui";
import { RateLimitedNotice } from "@/components/portfolio/states";

/**
 * `/portfolio` — Overview, the dashboard's landing page.
 *
 * Implements `docs/design/a-shadcn.html` (with the top-bar actions from
 * `a2-overview.html`). Everything it draws comes from `usePortfolio()`: the load,
 * the gates and the refresh/capture actions all live in the route layout, which
 * survives navigation to Holdings and Performance. This file is the answer to
 * "what does the reader see first" and nothing else.
 */
export default function PortfolioOverviewPage() {
  const {
    summary,
    demo,
    history,
    lastCapturedAt,
    holdings,
    loadingHoldings,
    throttle,
    sectorType,
    sectorSource,
    sectorError,
    sectorLoading,
    chooseSector,
    drillTypes,
    overview,
    setOverview,
  } = usePortfolio();

  return (
    <>
      <h1 className="text-xl font-semibold tracking-[-0.02em]">Portfolio</h1>
      <div className="mb-5 text-[13px] text-muted-foreground">
        {demo ? "Invented demo portfolio" : "Linked account snapshot"} · read{" "}
        {new Date(summary.as_of).toLocaleString("en-IN")}
      </div>

      {/* Above the numbers on purpose: if the history has stopped accruing, the
          reader needs to know that before they read a trend line drawn from it. */}
      <StalenessBanner lastCapturedAt={lastCapturedAt} />

      {throttle !== null ? (
        <div className="mb-4">
          <RateLimitedNotice retryAfter={throttle} />
        </div>
      ) : null}

      <StatCards
        summary={summary}
        holdingsCount={holdings.length}
        countIsPartial={loadingHoldings}
      />

      {/* AI overview (card A1). Streams its own metrics + narrative and degrades
          to "AI overview unavailable" on its own — it never blocks the rest of
          the dashboard, and every number here renders with or without the model.
          A completed run is kept in the layout's state and handed back as
          `cached`, so walking to Holdings and back re-reads it instead of paying
          five agents to re-say it. Regenerate still runs a fresh one. */}
      <AiOverview cached={overview} onComplete={setOverview} />

      <div className="mt-4 grid gap-4 lg:grid-cols-[2fr_1fr]">
        <NetWorthTrend points={history} lastCapturedAt={lastCapturedAt} />
        <Card>
          <CardHead title="Market cap mix" desc="Equity holdings by cap band" />
          <CapStrip slices={summary.by_market_cap} />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHead title="Allocation by asset type" desc="Share of current value" />
          <AllocationBars slices={summary.by_asset_type} labelMode="type" />
        </Card>
        <Card>
          <CardHead
            title="Allocation by sector"
            desc={
              sectorType
                ? `Within ${typeLabel(sectorType)} · fetched on demand`
                : "Whole portfolio, as the snapshot reports it"
            }
          />
          <div className="mb-3 flex flex-wrap gap-1.5">
            <Button
              variant={sectorType === null ? "primary" : "outline"}
              size="sm"
              onClick={() => chooseSector(null)}
            >
              Whole portfolio
            </Button>
            {drillTypes.map((type) => (
              <Button
                key={type}
                variant={sectorType === type ? "primary" : "outline"}
                size="sm"
                onClick={() => chooseSector(type)}
              >
                {typeLabel(type)}
              </Button>
            ))}
          </div>
          {sectorError ? (
            <div className="mb-2 text-xs text-muted-foreground">{sectorError}</div>
          ) : null}
          {sectorLoading ? (
            <AllocationBarsSkeleton />
          ) : (
            <AllocationBars slices={sectorSource} />
          )}
        </Card>
      </div>

      {demo ? (
        <div className="mt-4">
          <Badge variant="warn">
            Synthetic data — every name, value and identifier below is invented.
          </Badge>
        </div>
      ) : null}

      <PortfolioFooter demo={demo} />
    </>
  );
}
