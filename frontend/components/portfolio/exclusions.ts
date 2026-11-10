import type {
  AllocationSlice,
  HoldingExclusion,
  PortfolioHolding,
  PortfolioSummary,
} from "@/lib/api";

/**
 * Holdings the reader excluded, taken out of the live figures.
 *
 * The same arithmetic as `backend/services/exclusions.py::apply_to_snapshot`,
 * which the AI overview uses — history and movers are adjusted server-side and
 * arrive here already correct. The rules, on both sides:
 *
 * - An excluded row's value comes off its asset-type slice and the headline
 *   totals, its cost basis (where known) off `invested_total`, and the return
 *   is re-derived from what is left.
 * - **Never more than the source counted.** A row only comes off a bucket the
 *   summary actually reports, and never by more than that bucket's value — the
 *   #65 FD bucket has dropped out of the vendor's totals on some days, and
 *   subtracting from a total that never included it would invent a loss.
 * - Sector, cap-band and asset-class slices stay as reported: the source does
 *   not say which of them a row belongs to.
 *
 * Money is handled in integer paise so a subtraction cannot drift a rupee
 * figure by a float's rounding.
 */

export function holdingKey(source: string, externalId: string): string {
  return `${source}\u0000${externalId}`;
}

export interface ExclusionAdjustment {
  /** The summary with the excluded rows taken out. */
  summary: PortfolioSummary;
  /** What came off the totals, in rupees, and how many rows it took. */
  removedValue: number;
  removedInvested: number;
  removedCount: number;
  /** Exclusions with no matching row in hand — still loading, or gone at the source. */
  pending: number;
}

const toPaise = (value: string | null | undefined): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : null;
};

const fromPaise = (paise: number): string => (paise / 100).toFixed(2);

function bucketOf(assetType: string | null, raw: string | null): string | null {
  if (!assetType) return null;
  if (assetType === "UNKNOWN") return `UNKNOWN:${(raw ?? "").trim().toUpperCase()}`;
  return assetType;
}

/** `derive_pnl`: nothing from an unknown or zero cost basis. */
function derivePnl(current: number | null, invested: number | null): [string | null, string | null] {
  if (current === null || invested === null || invested === 0) return [null, null];
  const pnl = current - invested;
  return [fromPaise(pnl), ((pnl / invested) * 100).toFixed(2)];
}

export function applyExclusions(
  summary: PortfolioSummary,
  holdings: PortfolioHolding[],
  exclusions: HoldingExclusion[],
): ExclusionAdjustment {
  const unchanged: ExclusionAdjustment = {
    summary,
    removedValue: 0,
    removedInvested: 0,
    removedCount: 0,
    pending: exclusions.length,
  };
  if (!exclusions.length) return unchanged;

  const wanted = new Set(exclusions.map((e) => holdingKey(e.source, e.external_id)));
  const dropped = holdings.filter((h) => wanted.has(holdingKey(h.source, h.external_id)));
  const pending = exclusions.length - new Set(
    dropped.map((h) => holdingKey(h.source, h.external_id)),
  ).size;
  if (!dropped.length) return { ...unchanged, pending };

  const perBucket = new Map<string, { value: number; invested: number }>();
  for (const row of dropped) {
    const bucket = bucketOf(row.asset_type, row.asset_type_raw);
    if (!bucket) continue;
    const entry = perBucket.get(bucket) ?? { value: 0, invested: 0 };
    entry.value += toPaise(row.current_value) ?? 0;
    entry.invested += toPaise(row.invested_amount) ?? 0;
    perBucket.set(bucket, entry);
  }

  let removedValue = 0;
  let removedInvested = 0;
  const slices: AllocationSlice[] = [];
  for (const slice of summary.by_asset_type) {
    const bucket = bucketOf(slice.asset_type, slice.asset_type_raw);
    const entry = bucket ? perBucket.get(bucket) : undefined;
    if (!bucket || !entry) {
      slices.push(slice);
      continue;
    }
    perBucket.delete(bucket);
    const sliceValue = toPaise(slice.current_value) ?? 0;
    const sliceInvested = toPaise(slice.invested_amount);
    const value = Math.min(entry.value, sliceValue);
    const invested = sliceInvested === null ? 0 : Math.min(entry.invested, sliceInvested);
    removedValue += value;
    removedInvested += invested;
    const leftValue = sliceValue - value;
    let leftInvested = sliceInvested === null ? null : sliceInvested - invested;
    if (leftInvested !== null && leftInvested <= 0) leftInvested = null;
    if (leftValue <= 0 && leftInvested === null) continue;
    const [pnl, pnlPct] = derivePnl(leftValue, leftInvested);
    slices.push({
      ...slice,
      current_value: fromPaise(leftValue),
      invested_amount: leftInvested === null ? null : fromPaise(leftInvested),
      pnl,
      pnl_pct: pnlPct,
    });
  }

  if (removedValue === 0 && removedInvested === 0) {
    return { ...unchanged, pending };
  }

  const total = slices.reduce((sum, s) => sum + (toPaise(s.current_value) ?? 0), 0);
  const reweighted =
    total > 0
      ? slices.map((s) =>
          s.weight_pct === null
            ? s
            : { ...s, weight_pct: (((toPaise(s.current_value) ?? 0) / total) * 100).toFixed(2) },
        )
      : slices;

  const netWorth = toPaise(summary.net_worth);
  const current = toPaise(summary.current_value);
  let investedTotal = toPaise(summary.invested_total);
  if (investedTotal !== null) {
    investedTotal -= removedInvested;
    if (investedTotal <= 0) investedTotal = null;
  }
  const adjustedCurrent = current === null ? null : current - removedValue;
  const [pnl, pnlPct] = derivePnl(adjustedCurrent, investedTotal);

  return {
    summary: {
      ...summary,
      net_worth: netWorth === null ? summary.net_worth : fromPaise(netWorth - removedValue),
      current_value: adjustedCurrent === null ? null : fromPaise(adjustedCurrent),
      invested_total: investedTotal === null ? null : fromPaise(investedTotal),
      pnl,
      pnl_pct: pnlPct,
      by_asset_type: reweighted,
    },
    removedValue: removedValue / 100,
    removedInvested: removedInvested / 100,
    removedCount: dropped.length,
    pending,
  };
}
