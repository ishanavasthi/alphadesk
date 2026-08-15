"use client";

import type { AllocationSlice } from "@/lib/api";
import { inr, num, pct, shortLabel, typeLabel } from "./format";
import { Badge } from "./ui";

/**
 * Sorted, single-hue horizontal bars — the locked treatment for every
 * allocation breakdown.
 *
 * The rule from the dataviz pass is that **identity lives in the label**, not in
 * a colour: a categorical palette across asset types would imply a relationship
 * between hue and meaning that does not exist, and it stops working the moment
 * the source reports a bucket nobody assigned a colour to. One accent hue, bars
 * sorted by value, label on the left and `₹value · weight%` on the right.
 *
 * Bars are scaled against the **largest bucket**, not against the total: the
 * weights are printed beside every row, so the bar's job is comparison between
 * rows rather than a second, less precise statement of the same percentage.
 */
export function AllocationBars({
  slices,
  labelMode = "raw",
}: {
  slices: AllocationSlice[];
  /** `type` maps the source's asset-type enum to human labels. */
  labelMode?: "raw" | "type";
}) {
  const rows = slices
    .map((slice) => ({ slice, value: num(slice.current_value) ?? 0 }))
    .sort((a, b) => b.value - a.value);
  const max = rows.reduce((acc, row) => Math.max(acc, row.value), 0);

  if (!rows.length) {
    return <div className="py-2 text-[13px] text-muted-foreground">No buckets reported.</div>;
  }

  return (
    <div>
      {rows.map(({ slice, value }) => {
        const label =
          labelMode === "type"
            ? typeLabel(slice.asset_type, slice.asset_type_raw)
            : shortLabel(slice.label);
        const weight = num(slice.weight_pct);
        return (
          <div
            key={`${slice.label}-${slice.asset_type_raw ?? ""}`}
            className="adp-bar-row grid grid-cols-[90px_1fr_110px] items-center gap-2.5 py-[5px] sm:grid-cols-[110px_1fr_130px]"
            title={`${label} · ${inr(value)}${weight === null ? "" : ` · ${pct(weight)}`}`}
          >
            {/* Wraps rather than truncates: a clipped bucket label is a chart
                that has lost its only source of identity. */}
            <div className="text-[12.5px] leading-tight text-foreground">
              {label}
              {slice.us_exposure ? (
                <Badge variant="us" className="ml-1.5">
                  US
                </Badge>
              ) : null}
            </div>
            <div className="adp-track">
              <div
                className="adp-fill"
                style={{ width: max > 0 ? `${(value / max) * 100}%` : "2px" }}
              />
            </div>
            <div className="adp-num text-right text-xs text-muted-foreground">
              {inr(value)}
              {weight === null ? "" : ` · ${pct(weight)}`}
            </div>
          </div>
        );
      })}
    </div>
  );
}
