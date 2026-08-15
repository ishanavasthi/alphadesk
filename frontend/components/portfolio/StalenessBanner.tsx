"use client";

import { WarnBanner } from "./ui";
import { staleness, stalenessMessage } from "./staleness";

/**
 * "History paused — last captured N days ago."
 *
 * The locked amber treatment (`shadcn.css`), and `WarnBanner`'s first caller —
 * D1 built it for exactly this and left it unused because there was nothing to
 * be stale about yet.
 *
 * It renders **nothing** in two cases, both on purpose:
 *
 * - **fresh**: the newest capture is at least as new as the last day one was
 *   due for. Silence is the correct report.
 * - **never captured**: the trend card already says history starts with the
 *   first snapshot. A warning on top of an accurate empty state would read as a
 *   fault where there is none.
 *
 * `now` is injectable so the states are testable without freezing the clock.
 */
export function StalenessBanner({
  lastCapturedAt,
  now = new Date(),
}: {
  lastCapturedAt: string | null;
  now?: Date;
}) {
  const message = stalenessMessage(staleness(lastCapturedAt, now));
  if (message === null) return null;
  return (
    <WarnBanner>
      <span aria-hidden>⚠</span>
      <span>
        <b className="font-semibold">{message}</b>{" "}
        The nightly capture may have stopped — check the snapshot workflow. Days
        missed in the meantime cannot be recovered.
      </span>
    </WarnBanner>
  );
}
