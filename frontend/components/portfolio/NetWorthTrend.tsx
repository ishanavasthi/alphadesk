"use client";

import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardHead, EmptyCallout } from "./ui";
import { inr, lakh, num } from "./format";
import type { HistoryPoint } from "@/lib/api";

export interface TrendPoint {
  date: string;
  value: number;
}

/** API rows → chart rows. Unparseable or null values are dropped, not zeroed. */
export function toTrendPoints(points: HistoryPoint[]): TrendPoint[] {
  return points
    .map((point) => ({ date: point.date, value: num(point.net_worth) }))
    .filter((point): point is TrendPoint => point.value !== null);
}

function TrendTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: TrendPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="adp-num rounded-md bg-[#09090b] px-2.5 py-1.5 text-xs text-white">
      {point.date} · <b>{inr(point.value)}</b>
    </div>
  );
}

/**
 * The emphasized endpoint the chart rules call for.
 *
 * Recharts renders `dot` for every point or none, so "last point only" has to be
 * a render function that draws a circle at the final index and an empty `<g/>`
 * everywhere else. The white ring is what lifts it off the 7% area fill.
 */
function endpointDot(props: { cx?: number; cy?: number; index?: number; key?: string }, last: number) {
  const { cx, cy, index, key } = props;
  if (index !== last || cx === undefined || cy === undefined) {
    return <g key={key ?? `dot-${index}`} />;
  }
  return (
    <circle
      key={key ?? `dot-${index}`}
      cx={cx}
      cy={cy}
      r={3.5}
      fill="var(--adp-accent)"
      stroke="#fff"
      strokeWidth={1.5}
    />
  );
}

/**
 * Net-worth trend.
 *
 * **Renders whatever `points` it is given and invents nothing.** Until card S1
 * captures the first daily snapshot the API returns an empty list, and an empty
 * list draws the honest empty state below — not a flat line at today's value,
 * and not a synthesized series. When S1 starts filling `/portfolio/history`,
 * this component lights up with no change to it at all.
 *
 * Styling follows the locked chart rules: 2px accent line, 7% accent area,
 * emphasized endpoint, crosshair + tooltip on hover, y-axis in lakh.
 */
export function NetWorthTrend({
  points,
  lastCapturedAt,
}: {
  points: TrendPoint[];
  lastCapturedAt: string | null;
}) {
  const hasHistory = points.length > 1;

  return (
    <Card className="flex flex-col">
      <CardHead
        title="Net-worth trend"
        desc={
          hasHistory
            ? `${points.length} captured snapshots · ${lastCapturedAt ? `last ${lastCapturedAt}` : "daily"}`
            : "Daily snapshots · nothing captured yet"
        }
      />
      {hasHistory ? (
        <div className="h-[220px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points} margin={{ top: 12, right: 14, bottom: 4, left: 0 }}>
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                minTickGap={40}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                width={54}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11 }}
                // Function form, not the string form: Recharts only parses
                // "dataMin - N" / "dataMax + N" strings, so a multiplicative
                // string silently falls back to [0, dataMax] and flattens the
                // line against the top of the card.
                domain={[(min: number) => min * 0.985, (max: number) => max * 1.01]}
                tickFormatter={lakh}
              />
              <Tooltip
                content={<TrendTooltip />}
                cursor={{ stroke: "var(--adp-faint)", strokeDasharray: "3 3" }}
              />
              <Area
                type="linear"
                dataKey="value"
                stroke="none"
                fill="var(--adp-accent)"
                fillOpacity={0.07}
                isAnimationActive={false}
              />
              <Line
                type="linear"
                dataKey="value"
                stroke="var(--adp-accent)"
                strokeWidth={2}
                strokeLinejoin="round"
                isAnimationActive={false}
                dot={(dotProps) => endpointDot(dotProps, points.length - 1)}
                activeDot={{ r: 3.5, fill: "var(--adp-accent)", stroke: "#fff", strokeWidth: 1.5 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <EmptyCallout icon="◌" className="my-auto">
          <b className="font-semibold text-foreground">
            History starts with tonight&rsquo;s first snapshot.
          </b>{" "}
          {points.length === 1
            ? "One capture exists so far — a line needs two."
            : "Nothing has been captured yet, so there is no line to draw."}{" "}
          Today&rsquo;s totals are real; the history behind them begins accruing from the first
          nightly capture.
        </EmptyCallout>
      )}
    </Card>
  );
}
