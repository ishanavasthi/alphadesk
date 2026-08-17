/**
 * Number formatting for the portfolio surface.
 *
 * Two rules from `docs/design/DECISION.md`, and both of them are about honesty
 * rather than taste:
 *
 * - **INR everywhere**, `Intl.NumberFormat('en-IN')`, `₹` prefix, no decimals on
 *   amounts. The source converts foreign holdings to INR itself and publishes no
 *   currency field, so a `US` badge — not a `$` — is the exposure signal.
 * - **A masked number is not a missing number.** When the privacy toggle is on
 *   these helpers return a dot run, but `null` still returns `—`: "you chose to
 *   hide this" and "the source never reported this" are different facts and must
 *   not render as the same glyph. The `null` check therefore comes *first* in
 *   every helper below.
 * - **A missing number is `—`, never a computed zero.** Money arrives from the
 *   API as a decimal *string* (or `null`); `null` means the source did not
 *   report it, and every helper here keeps that distinction instead of coercing
 *   it to `0` on the way through.
 */

import { MASK, MASK_SHORT, amountsHidden } from "./privacy";

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const UNITS = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 4 });

/** Parse an API decimal string. `null` in, `null` out — never `0`. */
export function num(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** `₹10,07,655`, or `₹••••••` while amounts are hidden. */
export function inr(value: number | null): string {
  if (value === null) return "—";
  if (amountsHidden()) return `₹${MASK}`;
  return `₹${INR.format(Math.round(value))}`;
}

/**
 * `+₹88,905` / `−₹1,240`, using a real minus sign.
 *
 * The sign survives masking. It is not the number, the percentage beside it
 * already gives the direction away, and a P&L that hid whether it was a gain
 * would be hiding the wrong thing.
 */
export function inrSigned(value: number | null): string {
  if (value === null) return "—";
  const sign = value >= 0 ? "+" : "−";
  if (amountsHidden()) return `${sign}₹${MASK}`;
  return `${sign}₹${INR.format(Math.abs(Math.round(value)))}`;
}

/** `+8.4%` / `−100.0%`. */
export function pctSigned(value: number | null, digits = 1): string {
  if (value === null) return "—";
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}%`;
}

/** `24.2%` — an unsigned share, for weights. */
export function pct(value: number | null, digits = 1): string {
  if (value === null) return "—";
  return `${value.toFixed(digits)}%`;
}

/**
 * `10.2L` — the y-axis unit for a net-worth chart read by Indian users.
 *
 * Masked, this is the whole point of the feature: the trend *line* is a shape
 * and reveals nothing, but a labelled axis turns it back into a balance. The
 * ticks still render (the gridline positions are the shape), they just stop
 * naming a rupee figure.
 */
export function lakh(value: number): string {
  if (amountsHidden()) return MASK_SHORT;
  return `${(value / 100000).toFixed(1)}L`;
}

/**
 * Units held — masked alongside the amounts, and not as an afterthought.
 *
 * A holding's price sits in the next column and is a public number, so units
 * left visible multiply straight back into the position value. Hiding the
 * amount while publishing its two factors would be a toggle that only looks
 * like one.
 */
export function units(value: number | null): string {
  if (value === null) return "—";
  if (amountsHidden()) return MASK_SHORT;
  return UNITS.format(value);
}

/** Colour class for a signed figure. Status colours, never chart series. */
export function toneClass(value: number | null): string {
  if (value === null) return "text-[var(--adp-faint)]";
  return value >= 0 ? "text-[var(--adp-good)]" : "text-[var(--adp-bad)]";
}

/**
 * Human labels for the source's asset-type enum.
 *
 * Unlisted types fall back to the raw string: the enum has 16 members and the
 * source can also report buckets outside it (`US_STOCK_WALLET`), so a lookup
 * that pretended to be exhaustive would render a real holding as `undefined`.
 */
const TYPE_LABELS: Record<string, string> = {
  IND_STOCK: "Indian stocks",
  MF: "Mutual funds",
  US_STOCK: "US stocks",
  US_STOCK_WALLET: "US wallet cash",
  BOND: "Bonds",
  EPF: "EPF",
  NPS: "NPS",
  SA: "Savings",
  FD: "Fixed deposits",
  CRYPTO: "Crypto",
  INSURANCE: "Insurance",
  VEHICLE: "Vehicles",
  RE: "Real estate",
  RD: "Recurring deposits",
  AIF: "AIF",
  PMS: "PMS",
  PPF: "PPF",
};

export function typeLabel(assetType: string | null, raw?: string | null): string {
  const key = (raw || assetType || "").toUpperCase();
  return TYPE_LABELS[key] || raw || assetType || "Unknown";
}

/**
 * Order cap bands biggest → smallest.
 *
 * The ramp is sequential and the *order* is what carries its meaning, but the
 * source labels these buckets in its own words and C2 never pinned that
 * vocabulary. It really does return `Mega Cap` alongside large/mid/small, which
 * is one more band than the locked design drew — so this matches the words it
 * can recognise, and anything it cannot recognise keeps **the source's own
 * order** at the end rather than being sorted by a guess.
 */
export function orderCapBands<T extends { label: string }>(bands: T[]): T[] {
  const rank = (label: string): number => {
    const text = label.toLowerCase();
    if (text.includes("mega")) return 0;
    if (text.includes("large")) return 1;
    if (text.includes("mid")) return 2;
    if (text.includes("small")) return 3;
    if (text.includes("micro") || text.includes("nano")) return 4;
    return 5;
  };
  return bands
    .map((band, index) => ({ band, index, rank: rank(band.label) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((entry) => entry.band);
}

/**
 * The locked cap-band ramp (DECISION.md), ordered L → S.
 *
 * Tokens rather than literals: the ramp has a dark counterpart (`portfolio.css`)
 * and a chart that hard-coded the light hexes would keep drawing them on the
 * dark surface. Nothing here reads the theme — the browser resolves the
 * variables at paint time, which is also what makes the toggle instant.
 */
const CAP_STOPS = ["var(--adp-cap-1)", "var(--adp-cap-2)", "var(--adp-cap-3)"];

/**
 * `count` colours sampled from that ramp.
 *
 * The design drew three bands; the live source reports four. Cycling the three
 * stops would give the fourth band the *first* colour again and destroy the one
 * thing a sequential ramp asserts — that the step means further along the
 * order. Sampling the piecewise-linear gradient instead keeps lightness
 * monotonic for any number of bands, and reproduces the locked three exactly
 * when there are three.
 *
 * `color-mix(in srgb, …)` is the interpolation, not a rounder one: it is
 * per-channel linear over the same sRGB values the arithmetic used before, so
 * the four-band colours are byte-identical to the ones this shipped with.
 */
export function capRamp(count: number): string[] {
  if (count <= 1) return [CAP_STOPS[0]];
  const at = (t: number): string => {
    const span = t * (CAP_STOPS.length - 1);
    const index = Math.min(Math.floor(span), CAP_STOPS.length - 2);
    const frac = span - index;
    if (frac === 0) return CAP_STOPS[index];
    const weight = Math.round((1 - frac) * 10000) / 100;
    return `color-mix(in srgb, ${CAP_STOPS[index]} ${weight}%, ${CAP_STOPS[index + 1]})`;
  };
  return Array.from({ length: count }, (_, i) => at(i / (count - 1)));
}

/**
 * `Demo Cap Band Large` → `Large`. Bucket labels only.
 *
 * Matches the reference page, which trims the fixture's prefix so a bar label
 * fits its column. Holding *names* are never trimmed: on the demo path the
 * visible `Demo ` prefix is what tells a reader at a glance that none of these
 * positions are real.
 */
export function shortLabel(label: string): string {
  return label.replace(/^Demo Cap Band /i, "").replace(/^Demo /i, "");
}
