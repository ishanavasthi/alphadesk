"use client";

import { useMemo, useState } from "react";
import { CapStrip } from "@/components/portfolio/CapStrip";
import { NetWorthTrend } from "@/components/portfolio/NetWorthTrend";
import { usePortfolio } from "@/components/portfolio/PortfolioProvider";
import { StalenessBanner } from "@/components/portfolio/StalenessBanner";
import { inrSigned, pctSigned, toneClass } from "@/components/portfolio/format";
import { Button, Card, CardHead, PortfolioFooter } from "@/components/portfolio/ui";

/**
 * `/portfolio/performance` — the captured history, at full width.
 *
 * The staleness banner stays directly above the line for the same reason it sits
 * above the numbers on Overview: a trend drawn from a history that stopped
 * accruing has to say so before it is read. Days missed cannot be backfilled
 * from a point-in-time source, so the gap is the truth and the line is never
 * forward-filled to hide it.
 *
 * The window chips are the one thing this page adds. They are pure slices of the
 * year the provider already fetched — no request, no resampling, and no
 * interpolation to make a sparse window look continuous.
 */
const WINDOWS: Array<{ label: string; days: number }> = [
  { label: "30D", days: 30 },
  { label: "90D", days: 90 },
  { label: "1Y", days: 365 },
];

export default function PortfolioPerformancePage() {
  const { summary, demo, history, lastCapturedAt } = usePortfolio();
  const [days, setDays] = useState(90);

  /**
   * The window's points, counted back from the **most recent capture** rather
   * than from today.
   *
   * Anchoring on today would empty the 30D window entirely for an account whose
   * captures stopped six weeks ago — and an empty chart says "nothing was ever
   * captured", which is a different and false statement. The staleness banner
   * above already names the gap between the last capture and now; this chip
   * answers "the last 30 captured days", and it can always answer it.
   */
  const windowed = useMemo(() => {
    if (!history.length) return history;
    const last = new Date(`${history[history.length - 1].date}T00:00:00Z`);
    last.setUTCDate(last.getUTCDate() - (days - 1));
    const from = last.toISOString().slice(0, 10);
    return history.filter((point) => point.date >= from);
  }, [history, days]);

  // Change over the window: last − first, stated only when the window holds two
  // points to subtract. One point is a reading, not a change.
  const change = useMemo(() => {
    if (windowed.length < 2) return null;
    const first = windowed[0];
    const last = windowed[windowed.length - 1];
    const delta = last.value - first.value;
    return {
      delta,
      // A zero starting value has no percentage change, only an absolute one.
      pct: first.value === 0 ? null : (delta / first.value) * 100,
      from: first.date,
      to: last.date,
    };
  }, [windowed]);

  return (
    <>
      <StalenessBanner lastCapturedAt={lastCapturedAt} />

      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {WINDOWS.map((window) => (
          <Button
            key={window.label}
            variant={days === window.days ? "primary" : "outline"}
            size="sm"
            aria-pressed={days === window.days}
            onClick={() => setDays(window.days)}
          >
            {window.label}
          </Button>
        ))}
      </div>

      <NetWorthTrend
        points={windowed}
        lastCapturedAt={lastCapturedAt}
        caption={
          change ? (
            <>
              Change over window:{" "}
              <span className={`adp-num font-medium ${toneClass(change.delta)}`}>
                {inrSigned(change.delta)}
                {change.pct === null ? "" : ` · ${pctSigned(change.pct, 2)}`}
              </span>{" "}
              <span className="text-[var(--adp-faint)]">
                ({change.from} → {change.to}
                {change.pct === null ? ", no percentage from a zero start" : ""})
              </span>
            </>
          ) : (
            "Not enough captured days in this window to state a change — a change needs two snapshots to subtract."
          )
        }
      />

      <Card className="mt-4">
        <CardHead title="Market cap mix" desc="Equity holdings by cap band" />
        <CapStrip slices={summary.by_market_cap} />
      </Card>

      <PortfolioFooter demo={demo} />
    </>
  );
}
