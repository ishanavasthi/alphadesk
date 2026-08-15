/**
 * Number formatting for the portfolio surface.
 *
 * Two rules from `docs/design/DECISION.md`, and both of them are about honesty
 * rather than taste:
 *
 * - **INR everywhere**, `Intl.NumberFormat('en-IN')`, `₹` prefix, no decimals on
 *   amounts. The source converts foreign holdings to INR itself and publishes no
 *   currency field, so a `US` badge — not a `$` — is the exposure signal.
 * - **A missing number is `—`, never a computed zero.** Money arrives from the
 *   API as a decimal *string* (or `null`); `null` means the source did not
 *   report it, and every helper here keeps that distinction instead of coercing
 *   it to `0` on the way through.
 */

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const UNITS = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 4 });

/** Parse an API decimal string. `null` in, `null` out — never `0`. */
export function num(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** `₹10,07,655`. */
export function inr(value: number | null): string {
  if (value === null) return "—";
  return `₹${INR.format(Math.round(value))}`;
}

/** `+₹88,905` / `−₹1,240`, using a real minus sign. */
export function inrSigned(value: number | null): string {
  if (value === null) return "—";
  return `${value >= 0 ? "+" : "−"}₹${INR.format(Math.abs(Math.round(value)))}`;
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

/** `10.2L` — the y-axis unit for a net-worth chart read by Indian users. */
export function lakh(value: number): string {
  return `${(value / 100000).toFixed(1)}L`;
}

export function units(value: number | null): string {
  return value === null ? "—" : UNITS.format(value);
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

/** The locked cap-band ramp (DECISION.md), ordered darkest → lightest. */
const CAP_STOPS: Array<[number, number, number]> = [
  [0x1d, 0x4e, 0xd8],
  [0x60, 0xa5, 0xfa],
  [0xbf, 0xdb, 0xfe],
];

/**
 * `count` colours sampled from that ramp.
 *
 * The design drew three bands; the live source reports four. Cycling the three
 * stops would give the fourth band the *darkest* colour and destroy the one
 * thing a sequential ramp asserts — that darker means further along the order.
 * Sampling the piecewise-linear gradient instead keeps lightness monotonic for
 * any number of bands, and reproduces the locked three exactly when there are
 * three.
 */
export function capRamp(count: number): string[] {
  if (count <= 1) return [`rgb(${CAP_STOPS[0].join(",")})`];
  const at = (t: number): string => {
    const span = t * (CAP_STOPS.length - 1);
    const index = Math.min(Math.floor(span), CAP_STOPS.length - 2);
    const frac = span - index;
    const channel = (i: number) =>
      Math.round(CAP_STOPS[index][i] + (CAP_STOPS[index + 1][i] - CAP_STOPS[index][i]) * frac);
    return `rgb(${channel(0)},${channel(1)},${channel(2)})`;
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
