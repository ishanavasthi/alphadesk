"use client";

import type { ReactNode } from "react";
import type { PortfolioHolding } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { inr, inrSigned, num, pct, pctSigned, toneClass, typeLabel, units } from "./format";
import { Badge } from "./ui";

/** The one sentence behind every `—` in this dialog. */
const NOT_REPORTED = "Not reported by the source";

/**
 * One label/value line. `null` renders the labeled gap, never a computed zero.
 *
 * `note` is the sentence that turns a dash into a fact: a reader who sees `—`
 * beside "Sector" is owed the reason it is empty, otherwise the dash reads as a
 * bug in this page rather than a limit of the source.
 */
function Detail({
  label,
  children,
  note,
}: {
  label: string;
  children: ReactNode;
  note?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[var(--adp-hairline)] py-2 last:border-b-0">
      <dt className="text-[13px] text-muted-foreground">{label}</dt>
      <dd className="adp-num text-right text-[13px]">
        {children}
        {note ? <div className="text-[11.5px] text-[var(--adp-faint)]">{note}</div> : null}
      </dd>
    </div>
  );
}

/** `—` with the tooltip that says why. */
function Unknown() {
  return (
    <span className="cursor-help text-[var(--adp-faint)]" title={NOT_REPORTED}>
      —
    </span>
  );
}

/**
 * One position, in full.
 *
 * Every figure here is either a field of the row the holdings endpoint returned
 * or one division against the snapshot's own current value — there is no second
 * fetch and nothing is derived from an assumption. In particular:
 *
 * - **Return is stated only when a cost basis exists.** Same rule as the table:
 *   a row with no basis shows the labeled gap rather than a −100% invented from
 *   a missing number.
 * - **Sector and cap band are portfolio-level facts.** The source reports them
 *   as allocation slices, not per holding, so they render as named gaps here.
 *   Guessing a holding's sector from its name is exactly the kind of invention
 *   this surface refuses.
 * - **Share of portfolio** is this row's current value over the snapshot's
 *   current value — the source's own total, not a sum of the table (C2: the two
 *   legitimately disagree).
 */
export function HoldingDetailDialog({
  holding,
  portfolioValue,
  onClose,
}: {
  holding: PortfolioHolding | null;
  portfolioValue: number | null;
  onClose: () => void;
}) {
  if (!holding) return null;

  const invested = num(holding.invested_amount);
  const current = num(holding.current_value);
  const pnl = num(holding.pnl);
  const pnlPct = num(holding.pnl_pct);
  const share =
    current !== null && portfolioValue !== null && portfolioValue > 0
      ? (current / portfolioValue) * 100
      : null;

  const identifiers = [holding.symbol, holding.isin, holding.external_id].filter(Boolean);

  return (
    <Dialog open onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {holding.name || holding.symbol || holding.external_id}
            {holding.us_exposure ? (
              <Badge variant="us" className="ml-2 align-middle">
                US
              </Badge>
            ) : null}
          </DialogTitle>
          <DialogDescription>
            {identifiers.length ? identifiers.join(" · ") : NOT_REPORTED} · via {holding.source}
          </DialogDescription>
        </DialogHeader>

        <dl className="-mt-1">
          <Detail label="Asset type">
            <Badge variant="type">{typeLabel(holding.asset_type, holding.asset_type_raw)}</Badge>
          </Detail>
          <Detail label="Sector" note="reported per portfolio, not per holding">
            <Unknown />
          </Detail>
          <Detail label="Cap band" note="reported per portfolio, not per holding">
            <Unknown />
          </Detail>
          <Detail label="Units">
            {num(holding.units) === null ? <Unknown /> : units(num(holding.units))}
          </Detail>
          <Detail label="Average cost">
            {num(holding.avg_cost) === null ? <Unknown /> : inr(num(holding.avg_cost))}
          </Detail>
          <Detail label="Invested">
            {invested === null ? <Unknown /> : inr(invested)}
          </Detail>
          <Detail label="Current value">
            {current === null ? <Unknown /> : inr(current)}
          </Detail>
          <Detail
            label="Return"
            note={pnl === null && pnlPct === null ? "no cost basis reported" : undefined}
          >
            {pnl === null && pnlPct === null ? (
              <Unknown />
            ) : (
              <span className={toneClass(pnl ?? pnlPct)}>
                {pnl === null ? "—" : inrSigned(pnl)}
                {pnlPct === null ? "" : ` · ${pctSigned(pnlPct)}`}
              </span>
            )}
          </Detail>
          <Detail
            label="Share of portfolio"
            note={share === null ? undefined : "of the snapshot's current value"}
          >
            {share === null ? <Unknown /> : pct(share, 2)}
          </Detail>
        </dl>
      </DialogContent>
    </Dialog>
  );
}
