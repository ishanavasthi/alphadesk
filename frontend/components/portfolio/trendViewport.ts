/**
 * The arithmetic behind the trend chart's pan and zoom.
 *
 * Pure functions, kept out of the component so they can be tested without a
 * layout engine (jsdom has none, so Recharts draws nothing in a test). The
 * chart holds two pieces of view state, both in data units:
 *
 * - a **time window**, as inclusive point indices into the series, and
 * - a **price domain**, or `null` for auto-scale: fit to whatever is visible.
 *
 * Auto-scale pads by a share of the visible *range*, not of the value. Padding
 * by value (`min * 0.985`) was what pinned a sharp drop to the floor of the
 * card: on a 3L balance it adds ~4,500 below a fall of 70,000, so the last
 * point sat on the axis and read as a fall to nothing.
 */

export interface TimeWindow {
  start: number;
  end: number;
}

export type Domain = [number, number];

/** The fewest points a zoomed-in window may show. */
export const MIN_VISIBLE_POINTS = 5;

/** Share of the visible range left clear above and below the line. */
const RANGE_PAD = 0.12;

export function fullWindow(count: number): TimeWindow {
  return { start: 0, end: Math.max(0, count - 1) };
}

export function isFullWindow(window: TimeWindow, count: number): boolean {
  return window.start === 0 && window.end === Math.max(0, count - 1);
}

/** Smallest span (end − start) allowed for a series of `count` points. */
function minSpan(count: number): number {
  return Math.min(MIN_VISIBLE_POINTS - 1, Math.max(0, count - 1));
}

/**
 * Snap a fractional window onto whole indices inside the series, keeping its
 * span where it can. Drags and wheel steps produce fractions; the chart can
 * only draw whole points.
 */
export function clampWindow(start: number, end: number, count: number): TimeWindow {
  const last = Math.max(0, count - 1);
  let span = Math.round(end - start);
  span = Math.max(minSpan(count), Math.min(last, span));
  let from = Math.round(start);
  from = Math.max(0, Math.min(last - span, from));
  return { start: from, end: from + span };
}

/**
 * Zoom the time window by `factor` (< 1 zooms in) about `anchor`, the
 * cursor's position across the plot as a 0–1 fraction. The point under the
 * cursor stays under the cursor, which is what makes wheel zoom feel anchored.
 */
export function zoomWindow(
  window: TimeWindow,
  count: number,
  factor: number,
  anchor: number,
): TimeWindow {
  const span = window.end - window.start;
  const pivot = window.start + anchor * span;
  const nextSpan = Math.max(minSpan(count), Math.min(count - 1, span * factor));
  const start = pivot - anchor * nextSpan;
  return clampWindow(start, start + nextSpan, count);
}

/** Shift the time window by `delta` points, stopping at either end. */
export function panWindow(window: TimeWindow, count: number, delta: number): TimeWindow {
  return clampWindow(window.start + delta, window.end + delta, count);
}

/**
 * Auto-scale: the visible values plus a share of their range on each side.
 * A flat series has no range, so it gets a band of 1% of its level instead.
 */
export function fitDomain(values: number[]): Domain {
  if (values.length === 0) return [0, 1];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo;
  const pad = span > 0 ? span * RANGE_PAD : Math.max(Math.abs(hi) * 0.01, 1);
  return [lo - pad, hi + pad];
}

/** Stretch (`factor` < 1) or squash the price domain about its centre. */
export function scaleDomain([lo, hi]: Domain, factor: number): Domain {
  const mid = (lo + hi) / 2;
  const half = Math.max(((hi - lo) / 2) * factor, 1);
  return [mid - half, mid + half];
}

export function panDomain([lo, hi]: Domain, delta: number): Domain {
  return [lo + delta, hi + delta];
}

/**
 * Evenly spaced ticks on round numbers (1, 2, 2.5 or 5 × 10ⁿ) inside the
 * domain, about `target` of them. Recharts' own ticks on a fractional domain
 * land on arbitrary values, and once those are rounded to one decimal of a
 * lakh the labels come out unevenly spaced (3.5L, 3.1L, 2.8L, 2.6L).
 */
export function niceTicks([lo, hi]: Domain, target = 5): { ticks: number[]; step: number } {
  const raw = (hi - lo) / Math.max(1, target);
  if (!(raw > 0) || !Number.isFinite(raw)) return { ticks: [lo], step: 1 };
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? 10 * power;
  const ticks: number[] = [];
  for (let tick = Math.ceil(lo / step) * step; tick <= hi + step * 1e-9; tick += step) {
    // Repeated addition drifts (0.1 + 0.2); round each tick back onto the grid.
    ticks.push(Math.round(tick / step) * step);
  }
  return { ticks, step };
}

/** Decimals a lakh label needs so that adjacent ticks never print the same. */
export function lakhDigits(step: number): number {
  const inLakh = step / 100000;
  for (let digits = 0; digits < 4; digits += 1) {
    const scaled = inLakh * 10 ** digits;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-6) return digits;
  }
  return 4;
}
