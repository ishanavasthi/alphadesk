/**
 * Is the captured history still current? (card S1)
 *
 * Pure functions, no React, no fetch — because the interesting part is a date
 * rule and date rules are where this kind of feature quietly goes wrong. The
 * backend files every snapshot under an **IST calendar day with a 06:00 cutoff**
 * (`backend/services/snapshots.py`), and this module reproduces exactly that
 * rule so the two sides can never disagree about which day a timestamp belongs
 * to. If you change one, change both — there is a test on each side.
 *
 * Why a banner exists at all: GitHub disables scheduled workflows in a repo
 * with no activity for 60 days, and it does so silently. So does an expired
 * secret, a renamed Space and a failing deploy. The dashboard cannot detect any
 * of those individually, but it can notice that nothing has been captured — and
 * because the source is point-in-time, every day it stays unnoticed is a day of
 * history destroyed rather than delayed.
 */

/** IST is UTC+05:30, with no daylight saving since 1945. A constant, not a zone. */
export const IST_OFFSET_MINUTES = 330;

/** Captures before this IST hour belong to the previous IST calendar day. */
export const ATTRIBUTION_CUTOFF_HOUR = 6;

const MS_PER_DAY = 86_400_000;

/**
 * The IST calendar day a capture at `at` is filed under, as `YYYY-MM-DD`.
 *
 * The primary run is 23:45 IST and its retry is ~01:00 IST the next morning;
 * the cutoff is what makes both land on the same day. Implemented by shifting
 * the instant into IST and then reading **UTC** fields off the shifted value —
 * never local ones, because the reader's browser may be anywhere and the
 * attribution must not depend on where they opened the page.
 */
export function attributedDay(at: Date): string {
  const shifted = new Date(at.getTime() + IST_OFFSET_MINUTES * 60_000);
  if (shifted.getUTCHours() < ATTRIBUTION_CUTOFF_HOUR) {
    shifted.setUTCDate(shifted.getUTCDate() - 1);
  }
  return shifted.toISOString().slice(0, 10);
}

/**
 * The newest day a capture is definitely *due* for by `now`.
 *
 * One day behind `attributedDay`, deliberately: while the current attributed
 * day is `A`, `A`'s own capture runs at 23:45 IST — near the end of that
 * window — so expecting it would light the banner every morning at breakfast.
 * A banner that cries wolf daily is one the reader stops seeing, which costs
 * more than the extra day of latency buys.
 */
export function lastExpectedDay(now: Date): string {
  return addDays(attributedDay(now), -1);
}

export type Staleness =
  /** Nothing has ever been captured. Not a fault — a deployment with no past. */
  | { kind: "never" }
  | { kind: "fresh"; capturedOn: string }
  | { kind: "stale"; capturedOn: string; days: number };

/**
 * Classify `lastCapturedAt` (the API's `max(snapshot_days.captured_at)`).
 *
 * An unparseable timestamp is treated as `never` rather than as stale: claiming
 * "history paused" on the strength of a value we could not read would be
 * inventing a diagnosis.
 */
export function staleness(lastCapturedAt: string | null | undefined, now: Date): Staleness {
  if (!lastCapturedAt) return { kind: "never" };
  const at = new Date(lastCapturedAt);
  if (Number.isNaN(at.getTime())) return { kind: "never" };

  const capturedOn = attributedDay(at);
  const expected = lastExpectedDay(now);
  if (capturedOn >= expected) return { kind: "fresh", capturedOn };
  return { kind: "stale", capturedOn, days: daysBetween(capturedOn, attributedDay(now)) };
}

/**
 * The banner's text, or `null` when there should be no banner.
 *
 * `never` is deliberately silent: the trend card already says "history starts
 * with tonight's first snapshot", and stacking a warning on top of an accurate
 * empty state would read as a fault where there is none.
 */
export function stalenessMessage(state: Staleness): string | null {
  if (state.kind !== "stale") return null;
  return `History paused — last captured ${state.days} days ago (${state.capturedOn}).`;
}

/** `YYYY-MM-DD` arithmetic through UTC midnight, so no local zone leaks in. */
export function addDays(day: string, delta: number): string {
  const at = new Date(`${day}T00:00:00Z`);
  at.setUTCDate(at.getUTCDate() + delta);
  return at.toISOString().slice(0, 10);
}

export function daysBetween(from: string, to: string): number {
  const a = new Date(`${from}T00:00:00Z`).getTime();
  const b = new Date(`${to}T00:00:00Z`).getTime();
  return Math.round((b - a) / MS_PER_DAY);
}
