import { inr } from "./primitives";

/**
 * The miniature dashboard in the hero, ported from the locked landing demo.
 *
 * Every figure is synthetic and says so on the surface: a dashed "Synthetic
 * data" chip in its top bar and a "synthetic" caption under the trend. It
 * follows the same chart rules as the real dashboard (2px accent line over a 7%
 * area, sorted single hue allocation bars, the ordered cap ramp) so the landing
 * shows the product rather than an illustration of it.
 */

const W = 520;
const H = 150;
const PAD = { l: 40, r: 12, t: 10, b: 20 };

/** 26 weeks of synthetic weekly net worth, in rupees. */
const SERIES = [
  1042000, 1048500, 1039800, 1055200, 1061900, 1053400, 1070800, 1082300, 1076500, 1091200,
  1103800, 1096400, 1112700, 1121500, 1109900, 1127300, 1139600, 1131200, 1148900, 1160400,
  1152800, 1167300, 1174900, 1169500, 1179800, 1184620,
];

const MIN = Math.min(...SERIES) * 0.99;
const MAX = Math.max(...SERIES) * 1.008;
const px = (i: number) => PAD.l + ((W - PAD.l - PAD.r) * i) / (SERIES.length - 1);
const py = (v: number) => PAD.t + (H - PAD.t - PAD.b) * (1 - (v - MIN) / (MAX - MIN));

const LINE = SERIES.map((v, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(
  " ",
);
const AREA = `${LINE} L${px(SERIES.length - 1).toFixed(1)},${H - PAD.b} L${px(0).toFixed(1)},${H - PAD.b} Z`;
const GRID = [0, 1, 2].map((t) => {
  const value = MIN + ((MAX - MIN) * t) / 2;
  return { y: py(value), label: `${(value / 100000).toFixed(1)}L` };
});
const LAST = SERIES.length - 1;

/** Sorted largest to smallest: identity lives in the label, not in a hue. */
const ALLOCATION = [
  { label: "Mutual funds", value: 512400, pct: 43.3 },
  { label: "Indian stocks", value: 386900, pct: 32.7 },
  { label: "US stocks", value: 128300, pct: 10.8 },
  { label: "Fixed deposits", value: 94600, pct: 8.0 },
  { label: "Savings", value: 62420, pct: 5.3 },
].sort((a, b) => b.value - a.value);
const ALLOC_MAX = ALLOCATION[0].value;

const CAP_BANDS = [
  { label: "Large", value: 298900, token: "var(--adp-cap-1)" },
  { label: "Mid", value: 149400, token: "var(--adp-cap-2)" },
  { label: "Small", value: 66900, token: "var(--adp-cap-3)" },
];
const CAP_TOTAL = CAP_BANDS.reduce((sum, b) => sum + b.value, 0);

/**
 * The trend draws itself once, then stays drawn. Reduced motion gets the
 * finished line with no animation at all, which is the same picture.
 */
const TREND_CSS = `
.adl-line{stroke-dasharray:1;stroke-dashoffset:1;animation:adl-draw 1.5s cubic-bezier(.4,0,.2,1) .35s forwards}
.adl-area{opacity:0;animation:adl-area .6s ease 1.35s forwards}
.adl-dot{opacity:0;transform-origin:center;transform-box:fill-box;animation:adl-pop .35s cubic-bezier(.34,1.56,.64,1) 1.85s forwards}
@keyframes adl-draw{to{stroke-dashoffset:0}}
@keyframes adl-area{to{opacity:.07}}
@keyframes adl-pop{0%{opacity:0;transform:scale(.2)}100%{opacity:1;transform:scale(1)}}
@media (prefers-reduced-motion:reduce){
.adl-line,.adl-area,.adl-dot{animation:none}
.adl-line{stroke-dashoffset:0}
.adl-area{opacity:.07}
.adl-dot{opacity:1;transform:none}
}`;

function MockCard({
  title,
  desc,
  children,
  className,
}: {
  title: string;
  desc: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`min-w-0 rounded-lg border border-border p-3 shadow-[0_1px_2px_var(--adp-shadow)] ${className ?? ""}`}
    >
      <h3 className="text-[11.5px] font-semibold">{title}</h3>
      <div className="mb-2 text-[10.5px] text-muted-foreground">{desc}</div>
      {children}
    </div>
  );
}

export function DashboardMock() {
  return (
    <div
      role="img"
      aria-label="Miniature AlphaDesk dashboard on synthetic data: stat cards, a 26 week net worth trend, allocation bars, a market cap strip, holdings with one honest null, and a history staleness banner."
      className="min-w-0 rounded-xl border border-border bg-card p-3 text-xs shadow-[0_1px_2px_var(--adp-shadow),0_12px_32px_-16px_var(--adp-shadow)] sm:p-4"
    >
      <style dangerouslySetInnerHTML={{ __html: TREND_CSS }} />

      <div className="mb-3 flex items-center gap-2 border-b border-border px-0.5 pb-3">
        <span className="text-[13px] font-semibold">
          alpha<b className="font-semibold text-[var(--adp-accent)]">Desk</b>
        </span>
        <span className="text-[11.5px] text-[var(--adp-faint)]">/ Portfolio</span>
        <span className="flex-1" />
        <span className="hidden whitespace-nowrap rounded-full border border-border px-2 py-0.5 text-[10.5px] text-muted-foreground sm:inline">
          IND Money · linked
        </span>
        <span className="whitespace-nowrap rounded-full border border-dashed border-border px-2 py-0.5 text-[10.5px] text-muted-foreground">
          Synthetic data
        </span>
      </div>

      <div className="mb-2.5 grid grid-cols-3 gap-1.5 tabular-nums sm:gap-2">
        {[
          { label: "Net worth", value: "₹11,84,620", note: "after liabilities", tone: "" },
          {
            label: "Overall return",
            value: "+₹1,12,540",
            note: "+10.5% on invested",
            tone: "text-[var(--adp-good)]",
          },
          { label: "History", value: "182 days", note: "daily close snapshots", tone: "" },
        ].map((s) => (
          <div
            key={s.label}
            className="min-w-0 rounded-lg border border-border px-2 py-2 shadow-[0_1px_2px_var(--adp-shadow)] sm:px-3 sm:py-2.5"
          >
            <div className="whitespace-nowrap text-[10.5px] text-muted-foreground">{s.label}</div>
            <div className={`whitespace-nowrap text-sm font-semibold tracking-[-0.02em] sm:text-base ${s.tone}`}>
              {s.value}
            </div>
            <div className={`whitespace-nowrap text-[10px] ${s.tone || "text-[var(--adp-faint)]"}`}>
              {s.note}
            </div>
          </div>
        ))}
      </div>

      <MockCard
        title="Net worth trend"
        desc="26 weeks of daily snapshots · synthetic"
        className="mb-2.5"
      >
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" aria-hidden>
          {GRID.map((g) => (
            <g key={g.label}>
              <line
                x1={PAD.l}
                x2={W - PAD.r}
                y1={g.y}
                y2={g.y}
                stroke="var(--adp-hairline)"
              />
              <text
                x={PAD.l - 6}
                y={g.y + 3.5}
                textAnchor="end"
                fontSize="9"
                fill="var(--adp-faint)"
              >
                {g.label}
              </text>
            </g>
          ))}
          <path className="adl-area" d={AREA} fill="var(--adp-accent)" />
          <path
            className="adl-line"
            d={LINE}
            fill="none"
            stroke="var(--adp-accent)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
          />
          <circle
            className="adl-dot"
            cx={px(LAST)}
            cy={py(SERIES[LAST])}
            r="4"
            fill="var(--adp-accent)"
            stroke="var(--adp-dot-ring)"
            strokeWidth="2"
          />
          <text x={PAD.l} y={H - 6} fontSize="9" fill="var(--adp-faint)">
            W1
          </text>
          <text x={W - PAD.r} y={H - 6} textAnchor="end" fontSize="9" fill="var(--adp-faint)">
            W26
          </text>
        </svg>
      </MockCard>

      <div className="mb-2.5 grid gap-2.5 sm:grid-cols-2">
        <MockCard title="Allocation" desc="By asset type · share of value">
          <div className="tabular-nums">
            {ALLOCATION.map((row) => (
              <div key={row.label} className="grid grid-cols-[64px_1fr] items-center gap-2 py-[3px]">
                <div className="truncate text-[10.5px]">{row.label}</div>
                <div className="min-w-0">
                  <div className="relative h-3 overflow-hidden rounded-[3px] bg-[var(--adp-track)]">
                    <div
                      className="absolute inset-y-0 left-0 rounded-[3px] bg-[var(--adp-accent)]"
                      style={{ width: `${((row.value / ALLOC_MAX) * 100).toFixed(1)}%` }}
                    />
                  </div>
                  <div className="mt-px text-right text-[9.5px] text-muted-foreground">
                    {inr(row.value)} · {row.pct.toFixed(1)}%
                  </div>
                </div>
              </div>
            ))}
          </div>
        </MockCard>

        <MockCard title="Market cap mix" desc="Equity by cap band">
          <div className="flex h-[18px] gap-0.5 overflow-hidden rounded-[5px]">
            {CAP_BANDS.map((b) => (
              <div key={b.label} style={{ flex: b.value, background: b.token }} />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-2.5">
            {CAP_BANDS.map((b) => (
              <span
                key={b.label}
                className="flex items-center gap-1.5 text-[9.5px] text-muted-foreground"
              >
                <span
                  className="h-2 w-2 flex-none rounded-[2px]"
                  style={{ background: b.token }}
                  aria-hidden
                />
                {b.label} · {((b.value / CAP_TOTAL) * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        </MockCard>
      </div>

      <MockCard title="Holdings · honest nulls" desc="Sortable table · synthetic rows">
        <div className="tabular-nums">
          {[
            {
              ticker: "HDFCBANK",
              value: "₹2,41,300",
              why: "largest holding · 20.4% of net worth",
              verdict: "+12.4%",
              tone: "good" as const,
            },
            {
              ticker: "PPFAS FLEXI",
              value: "₹1,86,900",
              why: "SIP active · monthly",
              verdict: "+8.1%",
              tone: "good" as const,
            },
            {
              ticker: "SGB AUG30",
              value: "₹64,200",
              why: "cost basis not reported by the source",
              verdict: "\u2014",
              tone: "null" as const,
            },
          ].map((row) => (
            <div
              key={row.ticker}
              className="flex min-w-0 items-center gap-2 border-b border-[var(--adp-hairline)] px-0.5 py-1.5 last:border-b-0"
            >
              <span className="text-[11px] font-semibold tracking-[0.01em]">{row.ticker}</span>
              <span className="whitespace-nowrap text-[10.5px] text-muted-foreground">
                {row.value}
              </span>
              <span className="hidden flex-1 truncate text-right text-[10px] text-[var(--adp-faint)] sm:block">
                {row.why}
              </span>
              <span
                className={`flex-none rounded px-1.5 py-px text-[9.5px] font-semibold tracking-[0.05em] ${
                  row.tone === "good"
                    ? "border border-[var(--adp-good-bd)] bg-[var(--adp-good-bg)] text-[var(--adp-good-ink)]"
                    : "border border-border bg-[var(--adp-track)] text-muted-foreground"
                }`}
              >
                {row.verdict}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-center gap-2 rounded-md border border-[var(--adp-warn-bd)] bg-[var(--adp-warn-bg)] px-2.5 py-1.5 text-[10.5px] text-[var(--adp-warn-ink)]">
          <span aria-hidden>⏸</span>
          <span>
            <b className="font-semibold">History paused</b>, last captured 3 days ago. A missed
            snapshot cannot be backfilled.
          </span>
          <span className="ml-auto rounded-[5px] bg-primary px-2 py-0.5 text-[10px] text-primary-foreground">
            Details
          </span>
        </div>
      </MockCard>
    </div>
  );
}
