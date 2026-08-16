"use client";

import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { usePortfolio } from "@/components/portfolio/PortfolioProvider";
import { inr } from "@/components/portfolio/format";
import { Badge, Card, CardHead, PortfolioFooter } from "@/components/portfolio/ui";
import {
  RateLimitedNotice,
  SourceEmptyNotice,
  UnverifiedShapeNotice,
} from "@/components/portfolio/states";

/**
 * `/portfolio/holdings` — every row the source would give up, and a named gap
 * for every one it would not.
 *
 * The per-bucket notices below the table are the point of this page: a bucket
 * the snapshot reports but the holdings endpoint refuses (the EPF case), a row
 * shape this integration has never seen populated, a bucket the source
 * rate-limited away. None of them is allowed to render as an empty table,
 * because an empty table is a claim about what the reader owns.
 *
 * Nothing here fetches: the buckets were walked once by the layout's provider,
 * so arriving from Overview costs no calls against the source's per-minute
 * budget.
 */
export default function PortfolioHoldingsPage() {
  const { buckets, holdings, loadingHoldings, demo } = usePortfolio();

  return (
    <>
      {/* The badge rides the table it describes: this is the one page that
          prints invented *names and identifiers*, not just totals. */}
      {demo ? (
        <div className="mb-4">
          <Badge variant="warn">
            Synthetic data — every name, value and identifier below is invented.
          </Badge>
        </div>
      ) : null}

      <Card>
        <CardHead
          title="Holdings"
          desc={
            <>
              Click a column to sort · &ldquo;—&rdquo; means the source did not report a cost
              basis
              {loadingHoldings ? " · still loading buckets" : ""}
            </>
          }
        />
        <HoldingsTable rows={holdings} />
        {buckets.map((bucket) => {
          if (bucket.status === "unverified") {
            return <UnverifiedShapeNotice key={bucket.assetType} label={bucket.label} />;
          }
          if (bucket.status === "rate_limited") {
            return (
              <div key={bucket.assetType} className="mt-3.5">
                <RateLimitedNotice retryAfter={bucket.retryAfter} />
              </div>
            );
          }
          if (bucket.status === "unsupported") {
            return (
              <SourceEmptyNotice
                key={bucket.assetType}
                label={bucket.label}
                value={inr(bucket.reportedValue)}
              />
            );
          }
          if (bucket.status === "error") {
            return (
              <div key={bucket.assetType} className="mt-3.5 text-xs text-muted-foreground">
                {bucket.label} rows could not be read from the source.
              </div>
            );
          }
          if (!bucket.rows.length && (bucket.reportedValue ?? 0) > 0) {
            return (
              <SourceEmptyNotice
                key={bucket.assetType}
                label={bucket.label}
                value={inr(bucket.reportedValue)}
              />
            );
          }
          return null;
        })}
        {!holdings.length && !loadingHoldings ? (
          <div className="mt-3.5 text-[13px] text-muted-foreground">
            No holding-level rows were returned for any bucket in this snapshot.
          </div>
        ) : null}
      </Card>

      <PortfolioFooter demo={demo} />
    </>
  );
}
