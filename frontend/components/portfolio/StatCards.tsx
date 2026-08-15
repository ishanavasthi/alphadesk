"use client";

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
  note: string;
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
}: {
  summary: PortfolioSummary;
  holdingsCount: number;
  countIsPartial: boolean;
}) {
  const liabilities = num(summary.liabilities_total);
  const pnl = num(summary.pnl);
  const pnlPct = num(summary.pnl_pct);

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat
        label="Net worth"
        value={inr(num(summary.net_worth))}
        note={liabilities === null ? "as the source reports it" : `after ${inr(liabilities)} liabilities`}
      />
      <Stat
        label="Current value"
        value={inr(num(summary.current_value))}
        note={
          countIsPartial
            ? `across ${holdingsCount} holdings loaded so far`
            : `across ${holdingsCount} holdings`
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
