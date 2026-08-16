"use client";

import { demoDashboard } from "@/lib/demo";
import { AiOverview } from "@/components/portfolio/AiOverview";
import { AllocationBars } from "@/components/portfolio/AllocationBars";
import { CapStrip } from "@/components/portfolio/CapStrip";
import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { NetWorthTrend } from "@/components/portfolio/NetWorthTrend";
import { StatCards } from "@/components/portfolio/StatCards";
import { StalenessBanner } from "@/components/portfolio/StalenessBanner";
import { inr, num, typeLabel } from "@/components/portfolio/format";
import { Badge, Card, CardHead, PortfolioFooter } from "@/components/portfolio/ui";
import { SourceEmptyNotice } from "@/components/portfolio/states";

/**
 * The public `/demo` dashboard (card U1).
 *
 * The **same** D1 components the linked `/portfolio` renders, fed from committed
 * fixtures (`lib/demo`) instead of the network. It performs **no `fetch`**: no
 * `/portfolio/*` call, no `/portfolio/overview` stream, no LLM. `AiOverview`
 * receives card A1's frozen artifact through its static `initial` prop, so even
 * the narrative panel makes no request. Load it with the backend down and it
 * renders completely.
 *
 * Two deliberate differences from `/portfolio`, both because a public showcase
 * cannot make source calls:
 *
 * - **No sector drill-down chips.** Drilling fetches one `(asset_type, sector)`
 *   slice per click; the demo shows the whole-portfolio sector breakdown the
 *   snapshot already carries, and nothing more.
 * - **No Refresh / Capture top bar.** Those act on a live account; the demo has
 *   none. The persistent sample-data banner is the surface's chrome instead.
 */
export function DemoDashboard() {
  const { summary, buckets, overview } = demoDashboard;
  const holdings = buckets.flatMap((bucket) => bucket.rows);

  return (
    <>
      <h1 className="text-xl font-semibold tracking-[-0.02em]">Portfolio</h1>
      <div className="mb-5 text-[13px] text-muted-foreground">
        Invented demo portfolio · a linked account renders this page identically
      </div>

      {/* No captured history on the demo path — the banner stays silent (the
          trend card says history starts with the first snapshot), exactly as a
          real account with no snapshots yet would. */}
      <StalenessBanner lastCapturedAt={summary.last_captured_at} />

      <StatCards summary={summary} holdingsCount={holdings.length} countIsPartial={false} />

      {/* Card A1's committed overview, rendered statically — no stream, no LLM. */}
      <AiOverview initial={overview} />

      <div className="mt-4 grid gap-4 lg:grid-cols-[2fr_1fr]">
        <NetWorthTrend points={[]} lastCapturedAt={summary.last_captured_at} />
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
            desc="Whole portfolio, as the snapshot reports it"
          />
          <AllocationBars slices={summary.by_sector} />
        </Card>
      </div>

      <Card className="mt-4">
        <CardHead
          title="Holdings"
          desc={
            <>Click a column to sort · &ldquo;—&rdquo; means the source did not report a cost basis</>
          }
        />
        <HoldingsTable rows={holdings} portfolioValue={num(summary.current_value)} />
        {buckets.map((bucket) =>
          !bucket.rows.length && (bucket.reportedValue ?? 0) > 0 ? (
            <SourceEmptyNotice
              key={bucket.assetType}
              label={typeLabel(bucket.assetType, bucket.assetTypeRaw)}
              value={inr(bucket.reportedValue)}
            />
          ) : null,
        )}
      </Card>

      <div className="mt-4">
        <Badge variant="warn">
          Synthetic data — every name, value and identifier above is invented.
        </Badge>
      </div>

      <PortfolioFooter demo />
    </>
  );
}
