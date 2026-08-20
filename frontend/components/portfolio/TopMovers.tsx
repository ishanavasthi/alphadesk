"use client";

import { useEffect, useState } from "react";

import { getMovers, type MoverRow, type MoversResponse } from "@/lib/api";
import { Badge, Button, Card, CardHead, EmptyCallout } from "@/components/portfolio/ui";
import { inrSigned, num, pctSigned, toneClass } from "@/components/portfolio/format";
import { useAmountsHidden } from "@/components/portfolio/privacy";
import { addDays, attributedDay } from "@/components/portfolio/staleness";

/**
 * Top movers (card B8) — ranked gainers/losers over a chosen window.
 *
 * The card renders the groups the API already sorted rows into and **never
 * re-groups them**, because the grouping is the honest part: only `price`-basis
 * rows (units and a price at both ends) are a market move and get ranked;
 * `balance` rows are a deposit or a withdrawal and are shown apart, labelled as
 * money moved; `opened`/`closed` rows existed at one endpoint only and are
 * listed by name with no percentage at all — a position that appeared is not a
 * +100% gain, and printing one would be the single most misleading number this
 * surface could produce.
 *
 * The presets are the only arithmetic here. The API takes dates, so 1D/1W/1M/3M/
 * YTD are turned into `from`/`to` on this side, against the same **attributed**
 * IST day the capture service files snapshots under — asking for a window in
 * UTC "today" would ask for a day that may not have been captured yet. Whatever
 * the API snapped that request to comes back in `compared`, and when it differs
 * from `requested` the note says so rather than letting the reader assume the
 * dates on the button are the dates in the numbers.
 */

type PresetKey = "1D" | "1W" | "1M" | "3M" | "YTD";

const PRESETS: Array<{ key: PresetKey; label: string }> = [
  { key: "1D", label: "1D" },
  { key: "1W", label: "1W" },
  { key: "1M", label: "1M" },
  { key: "3M", label: "3M" },
  { key: "YTD", label: "YTD" },
];

/**
 * A preset → the `from`/`to` pair it asks the API for.
 *
 * `to` is always the current attributed day; `from` is a plain calendar offset
 * back from it (YTD being January 1st of that day's year). No snapping happens
 * here — the API owns that, because only it knows which days were captured.
 */
export function presetWindow(preset: PresetKey, now: Date): { from: string; to: string } {
  const to = attributedDay(now);
  if (preset === "YTD") return { from: `${to.slice(0, 4)}-01-01`, to };
  const back: Record<Exclude<PresetKey, "YTD">, number> = { "1D": 1, "1W": 7, "1M": 30, "3M": 90 };
  return { from: addDays(to, -back[preset]), to };
}

/** Name, then symbol, then the identity pair the API joined on. Never a guess. */
function rowLabel(row: MoverRow): string {
  return row.name || row.symbol || row.external_id;
}

function MoverLine({ row, showPct }: { row: MoverRow; showPct: boolean }) {
  const change = num(row.change_abs);
  return (
    <li className="flex items-baseline justify-between gap-3 border-b border-[var(--adp-hairline)] py-1.5 last:border-b-0">
      <span className="truncate text-[13px]">{rowLabel(row)}</span>
      <span className="adp-num flex shrink-0 items-baseline gap-2.5 text-[13px] tabular-nums">
        {showPct ? (
          <b className={`font-semibold ${toneClass(num(row.change_pct))}`}>
            {pctSigned(num(row.change_pct))}
          </b>
        ) : null}
        <span className={toneClass(change)}>{inrSigned(change)}</span>
      </span>
    </li>
  );
}

function MoverGroup({
  title,
  desc,
  rows,
  showPct = true,
  empty,
}: {
  title: string;
  desc?: string;
  rows: MoverRow[];
  showPct?: boolean;
  empty: string;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold">{title}</div>
      {desc ? <div className="mb-1.5 text-[11.5px] text-muted-foreground">{desc}</div> : null}
      {rows.length ? (
        <ul className="m-0 list-none p-0">
          {rows.map((row) => (
            <MoverLine key={`${row.source}:${row.external_id}`} row={row} showPct={showPct} />
          ))}
        </ul>
      ) : (
        <div className="py-1.5 text-[13px] text-muted-foreground">{empty}</div>
      )}
    </div>
  );
}

export function TopMovers() {
  const [preset, setPreset] = useState<PresetKey>("1W");
  const [data, setData] = useState<MoversResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Subscribing to the flag is what re-renders the amounts below when the eye
  // button flips; the formatters read it themselves, but nothing here is
  // otherwise a function of it and React would not know to paint again.
  useAmountsHidden();

  useEffect(() => {
    const controller = new AbortController();
    const { from, to } = presetWindow(preset, new Date());
    setLoading(true);
    setError(null);
    getMovers(from, to, 5, controller.signal)
      .then((payload) => {
        setData(payload);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (err.name === "AbortError") return;
        setData(null);
        setError(err.message);
        setLoading(false);
      });
    return () => controller.abort();
  }, [preset]);

  const compared = data?.compared;
  const ranked = (data?.gainers.length ?? 0) + (data?.losers.length ?? 0);
  const nothing =
    data !== null &&
    ranked === 0 &&
    data.flows.length === 0 &&
    data.opened.length === 0 &&
    data.closed.length === 0;

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <CardHead
          title="Top movers"
          desc={
            compared?.from && compared?.to
              ? `${compared.from} → ${compared.to} · from captured snapshots`
              : "Captured snapshots only · no fresh source call"
          }
        />
        <div className="flex shrink-0 flex-wrap gap-1.5">
          {PRESETS.map((option) => (
            <Button
              key={option.key}
              variant={preset === option.key ? "primary" : "outline"}
              size="sm"
              onClick={() => setPreset(option.key)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {data?.note ? (
        <div className="mb-3 text-xs text-muted-foreground">{data.note}</div>
      ) : null}

      {error ? (
        <EmptyCallout icon="!">{error}</EmptyCallout>
      ) : loading && data === null ? (
        <div className="py-2 text-[13px] text-muted-foreground">Reading captured days…</div>
      ) : nothing ? (
        <EmptyCallout icon="◌">
          <b className="font-semibold text-foreground">Nothing to compare yet.</b>{" "}
          Movers are computed between two captured days, so this fills in once the window contains
          at least two snapshots.
        </EmptyCallout>
      ) : data ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <MoverGroup
            title="Gainers"
            rows={data.gainers}
            empty="No priced holding gained over this window."
          />
          <MoverGroup
            title="Losers"
            rows={data.losers}
            empty="No priced holding lost over this window."
          />
          {data.flows.length ? (
            <div className="sm:col-span-2">
              <MoverGroup
                title="Money moved"
                desc="Deposits and withdrawals, not market movement — these are never ranked as movers."
                rows={data.flows}
                showPct={false}
                empty=""
              />
            </div>
          ) : null}
          {data.opened.length || data.closed.length ? (
            <div className="sm:col-span-2 text-[13px] text-muted-foreground">
              {data.opened.length ? (
                <div>
                  <b className="font-semibold text-foreground">Opened:</b>{" "}
                  {data.opened.map(rowLabel).join(", ")}
                </div>
              ) : null}
              {data.closed.length ? (
                <div>
                  <b className="font-semibold text-foreground">Closed:</b>{" "}
                  {data.closed.map(rowLabel).join(", ")}
                </div>
              ) : null}
              <div className="mt-0.5 text-xs">
                Present on only one of the two days, so there is no change to report.
              </div>
            </div>
          ) : null}
          {data.excluded.length ? (
            <div className="sm:col-span-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <span>Excluded as unknown:</span>
              {data.excluded.map((item) => (
                <Badge key={`${item.asset_type}:${item.reason}`} variant="warn">
                  {item.asset_type} — {item.reason}
                </Badge>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
