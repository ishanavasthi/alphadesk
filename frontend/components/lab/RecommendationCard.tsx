import { TrendingUp, TrendingDown, Target, Clock } from "lucide-react";
import { Card } from "@/components/ui/card";
import { ActionBadge, RiskBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import type { AnalystRecommendation, RiskAssessment } from "@/lib/api";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function ConfidenceBar({ value, tone }: { value: number; tone: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${pct}%`, background: tone }}
        />
      </div>
      <span className="w-9 text-right font-mono text-xs tabular-nums text-foreground">
        {pct}%
      </span>
    </div>
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
          {risk && <RiskBadge decision={risk.decision} />}
        </div>
      </div>

      {/* Confidence */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="eyebrow">Confidence</span>
          {rec.time_horizon && (
            <span className="flex items-center gap-1 font-mono text-[0.65rem] text-muted-foreground">
              <Clock className="h-3 w-3" />
              {rec.time_horizon}
            </span>
          )}
        </div>
        <ConfidenceBar value={rec.confidence} tone={tone} />
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

      {risk?.notes && (
        <p className="border-t border-border/60 pt-2 text-[0.7rem] italic text-muted-foreground">
          {risk.notes}
        </p>
      )}
    </Card>
  );
}
