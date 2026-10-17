"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardHead, EmptyCallout } from "@/components/ui/adp";
import { inr, lakh, num } from "./format";
import { attributedDay } from "./staleness";
import {
  fitDomain,
  fullWindow,
  isFullWindow,
  lakhDigits,
  niceTicks,
  panDomain,
  panWindow,
  scaleDomain,
  zoomWindow,
  type Domain,
  type TimeWindow,
} from "./trendViewport";
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
    <div className="adp-num rounded-md bg-[var(--adp-tooltip-bg)] px-2.5 py-1.5 text-xs text-[var(--adp-tooltip-ink)]">
      {point.date} · <b>{inr(point.value)}</b>
    </div>
  );
}

/**
 * The emphasized endpoint the chart rules call for.
 *
 * Recharts renders `dot` for every point or none, so "last point only" has to be
 * a render function that draws a circle at the final index and an empty `<g/>`
 * everywhere else. The ground-coloured ring is what lifts it off the 7% area
 * fill — a token, so it stays the ground in either theme.
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
      stroke="var(--adp-dot-ring)"
      strokeWidth={1.5}
    />
  );
}

// Plot geometry, shared by the Recharts props and the pointer maths that has to
// know where the plot sits inside the wrapper. Recharts gives an XAxis 30px by
// default; it is pinned here so the two cannot drift apart.
const Y_AXIS_WIDTH = 54;
const X_AXIS_HEIGHT = 30;
const MARGIN = { top: 12, right: 14, bottom: 4, left: 0 };

type Zone = "plot" | "price" | "time";

interface Drag {
  zone: Zone;
  pointerId: number;
  x: number;
  y: number;
  plotWidth: number;
  plotHeight: number;
  window: TimeWindow;
  domain: Domain;
  manualPrice: boolean;
}

interface View {
  window: TimeWindow;
  /** `null` is auto-scale: fit the price axis to whatever is visible. */
  price: Domain | null;
}

function plotBox(el: HTMLElement) {
  const rect = el.getBoundingClientRect();
  const left = rect.left + MARGIN.left + Y_AXIS_WIDTH;
  const right = rect.right - MARGIN.right;
  const top = rect.top + MARGIN.top;
  const bottom = rect.bottom - MARGIN.bottom - X_AXIS_HEIGHT;
  return { left, right, top, bottom, width: right - left, height: bottom - top };
}

function zoneAt(el: HTMLElement, clientX: number, clientY: number): Zone {
  const box = plotBox(el);
  if (clientX < box.left) return "price";
  if (clientY > box.bottom) return "time";
  return "plot";
}

const ZONE_CURSOR: Record<Zone, string> = {
  plot: "cursor-grab",
  price: "cursor-ns-resize",
  time: "cursor-ew-resize",
};

/**
 * The chart, with TradingView-style handling: drag the plot to pan through
 * time, scroll (or pinch on a trackpad) to zoom about the cursor, drag the
 * price axis to stretch or squash it, drag the date axis to zoom time.
 * Double-click the price axis to put it back on auto-scale, or the plot to
 * reset everything. Auto-scale fits the *visible* points, so zooming into a
 * window re-fits the axis to that window, as it does on TradingView.
 *
 * This is still a view over the points it is handed: pan and zoom choose which
 * of them to draw and where the axis sits; nothing is interpolated or added.
 */
function TrendChart({
  points,
  onViewChange,
  resetSignal,
}: {
  points: TrendPoint[];
  onViewChange: (changed: boolean) => void;
  resetSignal: number;
}) {
  const count = points.length;
  const [view, setView] = useState<View>(() => ({ window: fullWindow(count), price: null }));
  const wrapRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<Drag | null>(null);
  const [cursor, setCursor] = useState<string>(ZONE_CURSOR.plot);

  const visible = points.slice(view.window.start, view.window.end + 1);
  const domain = view.price ?? fitDomain(visible.map((point) => point.value));
  const { ticks, step } = niceTicks(domain);
  const digits = lakhDigits(step);
  const domainRef = useRef(domain);
  domainRef.current = domain;

  const changed = view.price !== null || !isFullWindow(view.window, count);
  useEffect(() => onViewChange(changed), [changed, onViewChange]);

  const reset = useCallback(() => setView({ window: fullWindow(count), price: null }), [count]);
  useEffect(() => {
    if (resetSignal > 0) reset();
  }, [resetSignal, reset]);

  // Wheel has to be a native listener: React registers `onWheel` as passive, and
  // a passive listener cannot stop the page scrolling under a zooming chart.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (zoneAt(el, event.clientX, event.clientY) !== "plot") return;
      event.preventDefault();
      const box = plotBox(el);
      // A sideways swipe pans; anything else zooms. Pixel-mode deltas from a
      // trackpad are small and many, line-mode ones from a mouse wheel few and
      // large, so line deltas are scaled up to a comparable step.
      const unit = event.deltaMode === 1 ? 16 : 1;
      const dx = event.deltaX * unit;
      const dy = event.deltaY * unit;
      setView((current) => {
        const span = current.window.end - current.window.start;
        if (Math.abs(dx) > Math.abs(dy)) {
          return { ...current, window: panWindow(current.window, count, (dx / box.width) * span) };
        }
        // Zoom about the cursor, except while today is on screen: then the
        // latest point stays pinned to the right edge, which is the point a
        // net-worth chart is read for and the easiest one to lose by accident.
        const anchor =
          current.window.end === count - 1
            ? 1
            : Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
        return {
          ...current,
          window: zoomWindow(current.window, count, Math.exp(dy * 0.0015), anchor),
        };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [count]);

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !wrapRef.current) return;
    const box = plotBox(wrapRef.current);
    const zone = zoneAt(wrapRef.current, event.clientX, event.clientY);
    dragRef.current = {
      zone,
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      plotWidth: box.width,
      plotHeight: box.height,
      window: view.window,
      domain: domainRef.current,
      manualPrice: view.price !== null,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    if (zone === "plot") setCursor("cursor-grabbing");
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      if (wrapRef.current) setCursor(ZONE_CURSOR[zoneAt(wrapRef.current, event.clientX, event.clientY)]);
      return;
    }
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    const span = drag.window.end - drag.window.start;
    const priceSpan = drag.domain[1] - drag.domain[0];
    if (drag.zone === "plot") {
      setView((current) => ({
        window: panWindow(drag.window, count, -(dx / drag.plotWidth) * span),
        // An auto-scaled axis follows the window; a hand-set one moves with the
        // drag, the way it does once TradingView's auto-scale is off.
        price: drag.manualPrice
          ? panDomain(drag.domain, (dy / drag.plotHeight) * priceSpan)
          : current.price,
      }));
    } else if (drag.zone === "price") {
      // Up stretches (zooms in), down squashes; exponential so the feel is the
      // same at any scale.
      setView((current) => ({ ...current, price: scaleDomain(drag.domain, Math.exp(dy * 0.006)) }));
    } else {
      // Right zooms in, left out, anchored at the latest point like TradingView.
      setView((current) => ({
        ...current,
        window: zoomWindow(drag.window, count, Math.exp(-dx * 0.006), 1),
      }));
    }
  }

  function onPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (wrapRef.current) setCursor(ZONE_CURSOR[zoneAt(wrapRef.current, event.clientX, event.clientY)]);
  }

  function onDoubleClick(event: ReactMouseEvent<HTMLDivElement>) {
    if (!wrapRef.current) return;
    const zone = zoneAt(wrapRef.current, event.clientX, event.clientY);
    if (zone === "price") setView((current) => ({ ...current, price: null }));
    else reset();
  }

  const lastVisible = view.window.end === count - 1 ? visible.length - 1 : -1;

  return (
    <div
      ref={wrapRef}
      className={`h-[220px] w-full select-none touch-pan-y ${cursor}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={onDoubleClick}
      title="Drag to pan · scroll to zoom · drag the price axis to rescale · double-click to reset"
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={visible} margin={MARGIN}>
          <XAxis
            dataKey="date"
            height={X_AXIS_HEIGHT}
            tickLine={false}
            axisLine={false}
            minTickGap={40}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            type="number"
            width={Y_AXIS_WIDTH}
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 11 }}
            // Explicit numbers, and `allowDataOverflow` so a hand-set axis clips
            // the line rather than Recharts quietly widening it back to fit.
            domain={domain}
            allowDataOverflow
            ticks={ticks}
            tickFormatter={(value: number) => lakh(value, digits)}
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
            dot={(dotProps) => endpointDot(dotProps, lastVisible)}
            activeDot={{
              r: 3.5,
              fill: "var(--adp-accent)",
              stroke: "var(--adp-dot-ring)",
              strokeWidth: 1.5,
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
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
 * emphasized endpoint, crosshair + tooltip on hover, y-axis in lakh. Pan and
 * zoom live in `TrendChart` above.
 *
 * `headLink` is the Overview card's way out to the full history; `caption` is
 * where Performance states the change over its selected window. Both are given
 * by the caller because the window arithmetic belongs to whoever chose the
 * window — this component still renders exactly the points it is handed.
 */
export function NetWorthTrend({
  points,
  lastCapturedAt,
  headLink,
  caption,
}: {
  points: TrendPoint[];
  lastCapturedAt: string | null;
  headLink?: { href: string; label: string };
  caption?: ReactNode;
}) {
  const hasHistory = points.length > 1;
  const [viewChanged, setViewChanged] = useState(false);
  const [resetSignal, setResetSignal] = useState(0);
  // The **attributed** day, not the raw timestamp: a capture that ran at 01:00
  // IST belongs to the previous day, and printing its wall-clock time here would
  // contradict the last point on the axis beside it. (It is also what stops a
  // microsecond-precision ISO string from appearing in a card subtitle.)
  const lastDay = lastCapturedAt ? attributedDay(new Date(lastCapturedAt)) : null;

  return (
    <Card className="flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <CardHead
          title="Net-worth trend"
          desc={
            hasHistory
              ? `${points.length} captured snapshots · ${lastDay ? `last ${lastDay}` : "daily"}`
              : "Daily snapshots · nothing captured yet"
          }
        />
        <div className="flex shrink-0 items-center gap-3">
          {hasHistory && viewChanged ? (
            <button
              type="button"
              onClick={() => setResetSignal((n) => n + 1)}
              className="text-xs text-muted-foreground hover:text-foreground hover:underline"
            >
              Reset view
            </button>
          ) : null}
          {headLink ? (
            <Link
              href={headLink.href}
              className="text-xs text-muted-foreground hover:text-foreground hover:underline"
            >
              {headLink.label}
            </Link>
          ) : null}
        </div>
      </div>
      {hasHistory ? (
        // Keyed on the series so a new window (30D → 1Y) starts from the full,
        // auto-scaled view instead of carrying a zoom meant for other data.
        <TrendChart
          key={`${points.length}:${points[0].date}:${points[points.length - 1].date}`}
          points={points}
          onViewChange={setViewChanged}
          resetSignal={resetSignal}
        />
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
      {caption ? (
        <div className="mt-3 border-t border-[var(--adp-hairline)] pt-3 text-[13px] text-muted-foreground">
          {caption}
        </div>
      ) : null}
    </Card>
  );
}
