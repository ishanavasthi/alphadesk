"use client";

import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { usePortfolio } from "@/components/portfolio/PortfolioProvider";
import { holdingKey } from "@/components/portfolio/exclusions";
import { inr, num, typeLabel } from "@/components/portfolio/format";
import { Badge, Button, Card, CardHead, SurfaceFooter } from "@/components/ui/adp";
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
  const {
    buckets,
    holdings,
    loadingHoldings,
    demo,
    adjusted,
    exclusions,
    excludedKeys,
    exclusionsBusy,
    exclusionsError,
    toggleExclusion,
    restoreExclusion,
  } = usePortfolio();
  const inHand = new Set(holdings.map((row) => holdingKey(row.source, row.external_id)));

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
              Click a column to sort, a row for detail or to exclude it from your totals ·
              &ldquo;—&rdquo; means the source did not report a cost basis
              {loadingHoldings ? " · still loading buckets" : ""}
            </>
          }
        />
        {exclusionsError ? (
          <div className="mb-3 text-xs text-[var(--adp-bad)]" role="alert">
            {exclusionsError}
          </div>
        ) : null}
        {/* The snapshot's own current value (less anything excluded), so the
            dialog can state a share without summing the table (C2: the two
            disagree). */}
        <HoldingsTable
          rows={holdings}
          portfolioValue={num(adjusted.summary.current_value)}
          excludedKeys={excludedKeys}
          busyKeys={exclusionsBusy}
          onToggleExclude={(row) => void toggleExclusion(row)}
        />
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

      {/* Every exclusion, including ones whose row the source no longer
          returns — those cannot be reached from the table, and an exclusion
          nobody can see is one nobody can undo. */}
      {exclusions.length ? (
        <Card className="mt-4">
          <CardHead
            title="Excluded from totals"
            desc="Left out of net worth, allocation, history, movers and the AI overview"
          />
          <ul className="m-0 list-none p-0">
            {exclusions.map((exclusion) => {
              const key = holdingKey(exclusion.source, exclusion.external_id);
              const busy = exclusionsBusy.has(key);
              return (
                <li
                  key={exclusion.id}
                  className="flex items-center justify-between gap-4 border-b border-[var(--adp-hairline)] py-2 last:border-b-0"
                >
                  <div className="text-[13px]">
                    <span className="font-medium">
                      {exclusion.name || exclusion.external_id}
                    </span>{" "}
                    <Badge variant="type">{typeLabel(exclusion.asset_type)}</Badge>
                    {!inHand.has(key) && !loadingHoldings ? (
                      <div className="text-[11.5px] text-muted-foreground">
                        not in the source&rsquo;s latest reading
                      </div>
                    ) : null}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void restoreExclusion(exclusion)}
                  >
                    {busy ? "Saving…" : "Include in totals"}
                  </Button>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}

      <SurfaceFooter demo={demo} />
    </>
  );
}
