"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { PortfolioSummary } from "@/lib/api";
import { inr, inrSigned, num, pctSigned, toneClass } from "./format";
import { Card } from "@/components/ui/adp";
import type { ExclusionAdjustment } from "./exclusions";

function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: ReactNode;
  tone?: string;
}) {
  return (
    <Card>
      <h3 className="text-[13px] font-medium text-muted-foreground">{label}</h3>
      <div className={`adp-num text-2xl font-semibold tracking-[-0.02em] ${tone ?? ""}`}>
        {value}
      </div>
      <div className="mt-0.5 text-xs text-[var(--adp-faint)]">{note}</div>
    </Card>
  );
}

/**
 * The four headline figures.
 *
 * `net worth` and `current value` are the **source's own totals**, passed
 * through — they are not sums of the holdings table and they will not agree with
 * it. C2 measured why: the source reports at least one bucket its holdings
 * endpoint cannot enumerate, and its snapshot and rows are priced from different
 * refreshes. Recomputing a total here to make the two match would replace a
 * measured number with a wrong one.
 *
 * `Overall return` is nullable for the same reason a row's is: with no cost
 * basis there is no return to state.
 */
export function StatCards({
  summary,
  holdingsCount,
  countIsPartial,
  holdingsHref,
  manual,
  excluded,
}: {
  summary: PortfolioSummary;
  holdingsCount: number;
  countIsPartial: boolean;
  /**
   * Where "See all holdings →" points, when there is somewhere to send the
   * reader. Opt-in because the public `/demo` renders these same cards on one
   * page and has no holdings route to link into.
   */
  holdingsHref?: string;
  /**
   * What the reader's manual fixed deposits add to the net worth (card B10).
   *
   * A **labelled** addition. The headline becomes the combined figure — that is
   * the number they asked this app to keep — but the subline names the addition
   * and repeats the source's own total beside it, so the vendor figure is never
   * silently replaced by one this app assembled. Absent (or zero rows) and this
   * card is byte-identical to before B10.
   */
  manual?: { total: number; count: number } | null;
  /**
   * Holdings the reader excluded from every figure (#65's misreported FDs).
   *
   * Like `manual`, a **labelled** adjustment: the headline figures are read
   * from `excluded.summary`, and each card names what came off so the source's
   * own total is never silently replaced. Absent or empty and the cards are
   * byte-identical to before.
   */
  excluded?: ExclusionAdjustment | null;
}) {
  const removed = excluded && excluded.removedCount > 0 ? excluded : null;
  const figures = removed ? removed.summary : summary;
  const liabilities = num(summary.liabilities_total);
  const pnl = num(figures.pnl);
  const pnlPct = num(figures.pnl_pct);

  const vendorNetWorth = num(summary.net_worth);
  const adjustedNetWorth = num(figures.net_worth);
  const added = manual && manual.count > 0 ? manual : null;
  const netWorth =
    added && adjustedNetWorth !== null ? adjustedNetWorth + added.total : adjustedNetWorth;
  const excludedNote = removed ? (
    <span className="adp-num">
      excl. {inr(removed.removedValue)} in {removed.removedCount} excluded holding
      {removed.removedCount === 1 ? "" : "s"}
    </span>
  ) : null;
  const sourceNote =
    liabilities === null ? "as the source reports it" : `after ${inr(liabilities)} liabilities`;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat
        label="Net worth"
        value={inr(netWorth)}
        note={
          added || removed ? (
            <>
              {added ? (
                <div className="adp-num">
                  incl. {inr(added.total)} in {added.count} manual FD
                  {added.count === 1 ? "" : "s"}
                </div>
              ) : null}
              {excludedNote ? <div>{excludedNote}</div> : null}
              <div className="adp-num">
                source reports {inr(vendorNetWorth)} · {sourceNote}
              </div>
            </>
          ) : (
            sourceNote
          )
        }
      />
      <Stat
        label="Current value"
        value={inr(num(figures.current_value))}
        note={
          <>
            {excludedNote ? <div>{excludedNote}</div> : null}
            {countIsPartial
              ? `across ${holdingsCount} holdings loaded so far`
              : `across ${holdingsCount} holdings`}{" "}
            {holdingsHref ? (
              <Link
                href={holdingsHref}
                className="whitespace-nowrap hover:text-foreground hover:underline"
              >
                See all holdings →
              </Link>
            ) : null}
          </>
        }
      />
      <Stat
        label="Invested"
        value={inr(num(figures.invested_total))}
        note={
          removed && removed.removedInvested > 0 ? (
            <span className="adp-num">
              where cost basis is known · excl. {inr(removed.removedInvested)} excluded
            </span>
          ) : (
            "where cost basis is known"
          )
        }
      />
      <Stat
        label="Overall return"
        value={pnl === null ? "—" : inrSigned(pnl)}
        tone={toneClass(pnl)}
        note={
          pnlPct === null
            ? "no cost basis reported — no return to state"
            : `${pctSigned(pnlPct, 2)} on invested amount`
        }
      />
    </div>
  );
}
