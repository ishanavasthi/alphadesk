"use client";

import Link from "next/link";

import { AppNav } from "@/components/shell/AppNav";
import { UserMenu } from "@/components/UserMenu";
import type { PortfolioSummary } from "@/lib/api";
import { Button, Chip } from "./ui";

/** The product surfaces, in the order they are offered everywhere. */
const NAV_LINKS = [
  { href: "/portfolio", label: "Portfolio" },
  { href: "/lab", label: "Lab" },
];

const LINK_LABEL: Record<PortfolioSummary["link_health"], { text: string; ok: boolean }> = {
  linked: { text: "IND Money · linked", ok: true },
  expiring: { text: "IND Money · renewing", ok: false },
  needs_relink: { text: "IND Money · relink needed", ok: false },
  revoked: { text: "IND Money · access revoked", ok: false },
};

/** What the Capture button is currently saying. */
export type CaptureState =
  | "idle"
  | "busy"
  | "done"
  | "existing"
  /** A capture this page did not start is already running — nothing failed. */
  | "in_flight"
  | "failed";

const CAPTURE_LABEL: Record<CaptureState, string> = {
  idle: "Capture snapshot",
  busy: "Capturing…",
  done: "Captured",
  existing: "Already captured today",
  in_flight: "Capturing in background…",
  failed: "Capture failed",
};

const CAPTURE_TITLE: Record<CaptureState, string> = {
  idle:
    "Take today's snapshot now. Idempotent — a day that already has one is left alone.",
  busy: "Reading every bucket the snapshot reports, paced against the source's rate limit.",
  done: "Today's snapshot is stored.",
  existing:
    "Today already has a snapshot. The first capture of a day is kept: it ran closest to the time it was timed for.",
  in_flight:
    "A capture for today was already running — opening this page starts one when the day is missing. It will finish on its own.",
  failed: "The source could not be read. Tonight's scheduled run will try again.",
};

/**
 * The surface's own top bar (`a-shadcn.html` / `a2-overview.html`).
 *
 * "Capture snapshot" is live as of S1. It is idempotent by construction — a day
 * that already has a row answers `already_captured` — so the honest label for a
 * second press is "already captured today", not a spinner that pretends to have
 * done something.
 *
 * "Refresh" carries a visible cooldown: one press re-walks every holdings
 * bucket, so the countdown shows the reader why the button is asleep rather than
 * letting them spend the source's rate limit discovering it.
 */
export function PortfolioTopBar({
  linkHealth,
  demo,
  onRefresh,
  refreshing,
  cooldown,
  onCapture,
  captureState = "idle",
}: {
  linkHealth: PortfolioSummary["link_health"] | null;
  demo: boolean;
  onRefresh: () => void;
  refreshing: boolean;
  /** Seconds left before another refresh is allowed; 0 means ready. */
  cooldown: number;
  onCapture: () => void;
  captureState?: CaptureState;
}) {
  const link = linkHealth ? LINK_LABEL[linkHealth] : null;
  // min-height, not height: the actions wrap to a second row at 375px, and a
  // fixed 56px header would let them spill over the page title.
  return (
    <header className="mb-6 flex min-h-14 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border py-2">
      {/* The dashboard overview *is* this surface's home, so the wordmark walks
          back to it from a drill-down rather than leaving the app. */}
      <Link href="/portfolio" className="font-semibold tracking-[-0.01em]">
        alpha<b className="text-[var(--adp-accent)]">Desk</b>
      </Link>
      {/* Replaces the static "/ Portfolio" breadcrumb: the same "you are here",
          but the Lab is one click away instead of a typed URL. */}
      <AppNav links={NAV_LINKS} className="text-[13px]" />
      <span className="flex-1" />
      <Button
        variant="outline"
        size="sm"
        onClick={onRefresh}
        disabled={refreshing || cooldown > 0}
        title={
          cooldown > 0 && !refreshing
            ? "A refresh re-reads every bucket from the source, which rate-limits per minute. Ready again shortly."
            : undefined
        }
      >
        ↺{" "}
        {refreshing ? "Refreshing…" : cooldown > 0 ? `Refresh · ${cooldown}s` : "Refresh"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={onCapture}
        disabled={captureState === "busy"}
        title={CAPTURE_TITLE[captureState]}
      >
        ◫ {CAPTURE_LABEL[captureState]}
      </Button>
      {link ? <Chip tone={link.ok ? "ok" : "warn"}>{link.text}</Chip> : null}
      {demo ? <Chip>Demo data</Chip> : null}
      {/* "Who are you" — the same flag-gated Clerk slot the Lab bar carries, so
          signing out and "Delete my data" are reachable without leaving the
          dashboard. Renders (and downloads) nothing when the flag is off. */}
      <UserMenu />
    </header>
  );
}
