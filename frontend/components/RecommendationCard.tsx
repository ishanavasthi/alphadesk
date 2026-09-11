import type { ReactNode } from "react";
import { TrendingUp, TrendingDown, Target, Clock } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ActionBadge, RiskBadge } from "@/components/StatusBadge";
import { Hint } from "@/components/Hint";
import { cn } from "@/lib/utils";
import type { AnalystRecommendation, RiskAssessment } from "@/lib/api";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function MeterBar({
  value,
  tone,
  muted,
}: {
  value: number;
  tone: string;
  muted?: boolean;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${pct}%`, background: tone }}
        />
      </div>
      <span
        className={cn(
          "w-9 text-right font-mono text-xs tabular-nums",
          muted ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {pct}%
      </span>
    </div>
  );
}

/**
 * The two numbers are deliberately drawn together (B11 phase 4). Conviction
 * alone reads as a quality score; next to an evidence bar that is honestly low,
 * it reads as what it is — a strong-ish opinion formed on very little data.
 */
function MeterLabel({
  text,
  head,
  hint,
}: {
  text: string;
  head: string;
  hint: ReactNode;
}) {
  return (
    <Hint
      content={
        <>
          <span className="hint-head">{head}</span>
          <span className="hint-body">{hint}</span>
        </>
      }
    >
      <span className="eyebrow border-b border-dotted border-muted-foreground/50">
        {text}
      </span>
    </Hint>
  );
}

function ChipRow({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="space-y-1">
      <div className="eyebrow">{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.map((it, i) => (
          <span
            key={i}
            className="rounded-sm border border-border bg-secondary/50 px-1.5 py-0.5 font-mono text-[0.65rem] text-muted-foreground"
          >
            {it}
          </span>
        ))}
      </div>
    </div>
  );
}

const TONE: Record<string, string> = {
  PASS: "var(--term-up)",
  FLAG: "var(--term-flag)",
  REJECT: "var(--term-down)",
};

export function RecommendationCard({
  rec,
  risk,
}: {
  rec: AnalystRecommendation;
  risk?: RiskAssessment;
}) {
  const tone = TONE[risk?.decision ?? "FLAG"] ?? "var(--term-flag)";

  return (
    <Card className="flex flex-col gap-3 p-4">
      {/* Header: ticker + sector / badges */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-lg font-bold leading-none tracking-tight text-primary">
            {rec.symbol}
          </div>
          {risk?.sector && (
            <div className="mt-1 eyebrow">{risk.sector}</div>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <ActionBadge action={rec.action} />
          {risk && <RiskBadge decision={risk.decision} flags={risk.flags} />}
        </div>
      </div>

      {/* Conviction + evidence. Never draw one without the other. */}
      <div className="space-y-2">
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <MeterLabel
              text="Conviction"
              head="Analyst · conviction"
              hint={
                <>
                  The model&apos;s own estimate that this call is directionally right
                  over the horizon - for a buy, that it beats the NIFTY 50. It is a{" "}
                  <strong>self-assessment, not a calibrated probability</strong>, and
                  has not been scored against outcomes.
                </>
              }
            />
            {rec.time_horizon && (
              <span className="flex items-center gap-1 font-mono text-[0.65rem] text-muted-foreground">
                <Clock className="h-3 w-3" />
                {rec.time_horizon}
              </span>
            )}
          </div>
          <MeterBar value={rec.confidence} tone={tone} />
        </div>

        {rec.evidence_quality != null && (
          <div className="space-y-1">
            <MeterLabel
              text="Evidence"
              head="Analyst · evidence"
              hint={
                <>
                  How much of that view rests on real data rather than inference. The
                  desk reads live price and the 52-week range only - no earnings,
                  valuation or filings - so this is <strong>low by construction</strong>.
                  A high conviction on a low evidence base is an opinion, not a finding.
                </>
              }
            />
            <MeterBar
              value={rec.evidence_quality}
              tone="hsl(var(--muted-foreground))"
              muted
            />
          </div>
        )}
      </div>

      {/* Target price */}
      {rec.target_price != null && (
        <div className="flex items-center gap-2 border-y border-border/60 py-2">
          <Target className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="eyebrow">Target</span>
          <span className="ml-auto font-mono text-sm tabular-nums text-foreground">
            ₹{inr.format(rec.target_price)}
          </span>
        </div>
      )}

      {/* Bull / Bear */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div className="rounded-sm border-l-2 border-l-up bg-up-soft p-2">
          <div className="mb-1 flex items-center gap-1.5">
            <TrendingUp className="h-3 w-3 text-up" />
            <span className="eyebrow text-up">Bull</span>
          </div>
          <p className="text-[0.78rem] leading-snug text-foreground/85">{rec.bull_thesis}</p>
        </div>
        <div className="rounded-sm border-l-2 border-l-down bg-down-soft p-2">
          <div className="mb-1 flex items-center gap-1.5">
            <TrendingDown className="h-3 w-3 text-down" />
            <span className="eyebrow text-down">Bear</span>
          </div>
          <p className="text-[0.78rem] leading-snug text-foreground/85">{rec.bear_thesis}</p>
        </div>
      </div>

      <ChipRow label="Catalysts" items={rec.catalysts} />
      <ChipRow label="Key risks" items={rec.key_risks} />
      <ChipRow label="Data gaps" items={rec.data_gaps ?? []} />

      {risk?.notes && (
        <p className="border-t border-border/60 pt-2 text-[0.7rem] italic text-muted-foreground">
          {risk.notes}
        </p>
      )}
    </Card>
  );
}
