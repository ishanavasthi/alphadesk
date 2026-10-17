import { describe, expect, it } from "vitest";

import { lakh } from "@/components/portfolio/format";
import {
  clampWindow,
  fitDomain,
  fullWindow,
  isFullWindow,
  lakhDigits,
  niceTicks,
  panWindow,
  scaleDomain,
  zoomWindow,
} from "@/components/portfolio/trendViewport";

describe("auto-scale", () => {
  it("keeps a sharp drop off the floor of the chart", () => {
    // The 2026-10-16 shape: ~3.3L for weeks, then one day at ~2.65L.
    const values = [330000, 335000, 340000, 334000, 265000];
    const [lo, hi] = fitDomain(values);
    const span = 340000 - 265000;
    // Clear space below the lowest point, measured against the range, so
    // the last point no longer sits on the axis.
    expect(265000 - lo).toBeCloseTo(span * 0.12);
    expect(hi - 340000).toBeCloseTo(span * 0.12);
  });

  it("gives a flat series a band instead of a zero-height axis", () => {
    const [lo, hi] = fitDomain([300000, 300000]);
    expect(lo).toBeLessThan(300000);
    expect(hi).toBeGreaterThan(300000);
  });
});

describe("ticks", () => {
  it("lands on evenly spaced round values", () => {
    const { ticks, step } = niceTicks([256000, 349000]);
    expect(step).toBe(20000);
    expect(ticks).toEqual([260000, 280000, 300000, 320000, 340000]);
    const gaps = ticks.slice(1).map((tick, i) => tick - ticks[i]);
    expect(new Set(gaps).size).toBe(1);
  });

  it("prints enough decimals that neighbouring ticks never read the same", () => {
    const { ticks, step } = niceTicks([256000, 349000], 4);
    const labels = ticks.map((tick) => lakh(tick, lakhDigits(step)));
    expect(labels).toEqual(["2.75L", "3.00L", "3.25L"]);
    expect(lakhDigits(100000)).toBe(0);
    expect(lakhDigits(50000)).toBe(1);
    expect(lakhDigits(5000)).toBe(2);
  });
});

describe("time window", () => {
  const count = 61;

  it("starts on the whole series", () => {
    expect(fullWindow(count)).toEqual({ start: 0, end: 60 });
    expect(isFullWindow(fullWindow(count), count)).toBe(true);
  });

  it("zooms about the cursor and keeps the point under it in place", () => {
    const zoomed = zoomWindow(fullWindow(count), count, 0.5, 1);
    // Anchored on the right edge: the latest point stays, the span halves.
    expect(zoomed).toEqual({ start: 30, end: 60 });
    const centred = zoomWindow(fullWindow(count), count, 0.5, 0.5);
    expect(centred).toEqual({ start: 15, end: 45 });
  });

  it("never zooms past the minimum window or beyond the series", () => {
    expect(zoomWindow(fullWindow(count), count, 0.001, 1)).toEqual({ start: 56, end: 60 });
    expect(zoomWindow({ start: 20, end: 30 }, count, 100, 0.5)).toEqual({ start: 0, end: 60 });
    // A two-point series has nothing to zoom into.
    expect(zoomWindow(fullWindow(2), 2, 0.1, 0.5)).toEqual({ start: 0, end: 1 });
  });

  it("pans without losing span, and stops at either end", () => {
    expect(panWindow({ start: 10, end: 20 }, count, 5)).toEqual({ start: 15, end: 25 });
    expect(panWindow({ start: 10, end: 20 }, count, 100)).toEqual({ start: 50, end: 60 });
    expect(panWindow({ start: 10, end: 20 }, count, -100)).toEqual({ start: 0, end: 10 });
    expect(clampWindow(3.4, 13.6, count)).toEqual({ start: 3, end: 13 });
  });
});

describe("price axis", () => {
  it("stretches and squashes about the centre", () => {
    expect(scaleDomain([200000, 400000], 0.5)).toEqual([250000, 350000]);
    expect(scaleDomain([200000, 400000], 2)).toEqual([100000, 500000]);
  });
});
