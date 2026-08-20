"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { PortfolioSummary } from "@/lib/api";
import { inr, inrSigned, num, pctSigned, toneClass } from "./format";
import { Card } from "./ui";

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
}) {
  const liabilities = num(summary.liabilities_total);
  const pnl = num(summary.pnl);
  const pnlPct = num(summary.pnl_pct);

  const vendorNetWorth = num(summary.net_worth);
  const added = manual && manual.count > 0 ? manual : null;
  const netWorth =
    added && vendorNetWorth !== null ? vendorNetWorth + added.total : vendorNetWorth;
  const sourceNote =
    liabilities === null ? "as the source reports it" : `after ${inr(liabilities)} liabilities`;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat
        label="Net worth"
        value={inr(netWorth)}
        note={
          added ? (
            <>
              <span className="adp-num">
                incl. {inr(added.total)} in {added.count} manual FD
                {added.count === 1 ? "" : "s"}
              </span>
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
        value={inr(num(summary.current_value))}
        note={
          <>
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
        value={inr(num(summary.invested_total))}
        note="where cost basis is known"
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
