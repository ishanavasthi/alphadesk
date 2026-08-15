"use client";

import type { AllocationSlice } from "@/lib/api";
import { capRamp, inr, num, orderCapBands, pct, shortLabel } from "./format";

/**
 * Market-cap mix: a three-segment stacked strip in the ordered sequential ramp.
 *
 * Cap bands are **ordered** (biggest → smallest), so they get the sequential
 * ramp rather than the single accent hue — the colour carries the ordering, and
 * the ramp was validated OKLab-monotonic at D0 so the steps read as steps in
 * both directions. Legend chips carry the labels; nothing depends on colour
 * alone. The band count comes from the source (four in the live account, three
 * in the demo fixture), so the ramp is sampled rather than indexed.
 */
export function CapStrip({ slices }: { slices: AllocationSlice[] }) {
  const bands = orderCapBands(slices).map((slice) => ({
    slice,
    value: num(slice.current_value) ?? 0,
  }));
  const total = bands.reduce((sum, band) => sum + band.value, 0);
  const ramp = capRamp(bands.length);

  if (!bands.length || total <= 0) {
    return (
      <div className="py-2 text-[13px] text-muted-foreground">
        The source reports no cap-band split for this portfolio.
      </div>
    );
  }

  return (
    <div>
      <div className="flex h-[26px] gap-0.5 overflow-hidden rounded-md">
        {bands.map(({ slice, value }, index) => (
          <div
            key={slice.label}
            style={{ flex: value, background: ramp[index] }}
            title={`${shortLabel(slice.label)} · ${inr(value)} · ${pct((value / total) * 100)}`}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-4">
        {bands.map(({ slice, value }, index) => (
          <span
            key={slice.label}
            className="flex items-center gap-1.5 text-xs text-muted-foreground"
          >
            <span
              className="h-2.5 w-2.5 rounded-[3px]"
              style={{ background: ramp[index] }}
              aria-hidden
            />
            <span className="adp-num">
              {shortLabel(slice.label)} · {pct((value / total) * 100, 0)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
