"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { AUTH_ENABLED } from "@/lib/auth";

/**
 * Greeting block above the portfolio summary (issue #41).
 *
 * A time-of-day greeting with the reader's first name, a static market-mood
 * line, and a `fetched N ago` timestamp. Four deliberate constraints from the
 * issue, each pinned by a test:
 *
 * 1. **IST.** The greeting keys off Asia/Kolkata, the same day S1's
 *    `attributed_day` owns — two parts of the app must never disagree about
 *    what time of day it is.
 * 2. **No name is normal.** Single-tenant dev and signed-out readers have no
 *    Clerk identity; the greeting ends at the daypart, never at a dangling
 *    comma. The name arrives (if at all) through a flag-gated dynamic import
 *    of `ClerkFirstName`, so flag-off downloads no Clerk.
 * 3. **"fetched", never "as of".** No payload carries a date — the connector
 *    stamps `as_of` at fetch time — so "prices as of 3:42pm" would be a
 *    freshness claim we cannot make.
 * 4. **The mood line is a static rotation, not an LLM call.** A per-pageload
 *    generation would be an uncapped spend path on a page that must always
 *    render, and whatever it claims keys off the total P&L we actually hold —
 *    never a day move (Day's P&L is its own ticket) and never a forecast.
 *    Rotation is deterministic per IST day, so server and client render agree.
 */

const ClerkFirstName = AUTH_ENABLED
  ? dynamic(
      () =>
        import("@/components/clerk/ClerkFirstName").then((mod) => mod.ClerkFirstName),
      { ssr: false },
    )
  : () => null;

/** Static mood lines, keyed to the sign of the total P&L we actually hold. */
export const MOOD_UP = [
  "In the green overall — the winners are doing the heavy lifting.",
  "Above water on the whole book. Not a bad page to open.",
  "Green across the total — let the trend do the talking.",
] as const;

export const MOOD_DOWN = [
  "Underwater overall — the trend line matters more than today.",
  "In the red on the whole book. Boring compounding beats loud days.",
  "Below cost overall — this page is for watching, not reacting.",
] as const;

export const MOOD_FLAT = [
  "Steady as she goes — nothing in the book is shouting.",
  "A quiet book. The dashboard will tell you when that changes.",
  "Flat overall — no drama, which is a perfectly good day.",
] as const;

/** Daypart in IST. Exported for tests; the app reads it through `greeting`. */
export function daypart(now: Date = new Date()): "morning" | "afternoon" | "evening" {
  // `hour12: false` renders midnight IST as "24" — fold it back to 0.
  const hour =
    Number(
      new Intl.DateTimeFormat("en-IN", {
        hour: "numeric",
        hour12: false,
        timeZone: "Asia/Kolkata",
      }).format(now),
    ) % 24;
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  return "evening";
}

/** Deterministic pick: the IST day-of-year selects the line, so SSR == client. */
export function moodLine(pnl: number | null, now: Date = new Date()): string {
  const lines = pnl === null || pnl === 0 ? MOOD_FLAT : pnl > 0 ? MOOD_UP : MOOD_DOWN;
  const istDay = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).format(now);
  let hash = 0;
  for (let i = 0; i < istDay.length; i += 1) hash = (hash * 31 + istDay.charCodeAt(i)) >>> 0;
  return lines[hash % lines.length];
}

/** `fetched 4 min ago` — relative, honest, and never "as of". */
export function fetchedAgo(asOf: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(asOf).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** The pure block: everything testable, with the name already resolved. */
export function GreetingBlock({
  name,
  asOf,
  pnl,
  demo,
  now,
}: {
  name: string | null;
  asOf: string;
  pnl: number | null;
  demo: boolean;
  now?: Date;
}) {
  const at = now ?? new Date();
  const hello = `Good ${daypart(at)}${name ? `, ${name}` : ""}.`;
  return (
    <div className="mb-5">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">{hello}</h1>
      <div className="mt-1 text-[13px] text-muted-foreground">{moodLine(pnl, at)}</div>
      <div className="mt-1 text-[13px] text-muted-foreground">
        {demo ? "Invented demo portfolio" : "Linked account snapshot"} · fetched{" "}
        {fetchedAgo(asOf, at)}
      </div>
    </div>
  );
}

/** The wired block: resolves the name through Clerk when there is one. */
export function Greeting({
  asOf,
  pnl,
  demo,
}: {
  asOf: string;
  pnl: number | null;
  demo: boolean;
}) {
  const [name, setName] = useState<string | null>(null);
  return (
    <>
      <ClerkFirstName onName={setName} />
      <GreetingBlock name={name} asOf={asOf} pnl={pnl} demo={demo} />
    </>
  );
}
