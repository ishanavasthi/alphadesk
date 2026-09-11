import type { ReactNode } from "react";

import { Hint, HintHead } from "@/components/lab/Hint";
import { ActionBadge, RiskBadge } from "@/components/lab/StatusBadge";
import { Card } from "@/components/ui/adp";
import { cn } from "@/lib/utils";
import type { AnalystRecommendation, RiskAssessment } from "@/lib/api";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/**
 * A magnitude bar, drawn in one hue.
 *
 * **No threshold ticks.** The design mock (`docs/design/lab/a-console.html`)
 * drew conviction against the 0.70 floor and the 0.75 pass line, and B11 then
 * measured the model and found rerun noise larger than the between-stock
 * spread: there is no cut point, and the thresholds that remain are a collapse
 * detector, not a quality bar. Drawing a line the number cannot meaningfully sit
 * either side of would be the most confident-looking thing on the card and the
 * least true. The verdict is the badge's job.
 */
function MeterBar({ value, muted }: { value: number; muted?: boolean }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="adp-meter flex-1">
        <div
          className="adp-meter-fill"
          style={{
            width: `${pct}%`,
            background: muted ? "hsl(var(--muted-foreground))" : undefined,
          }}
        />
      </div>
      <span
        className={cn(
          "adp-num w-9 text-right text-xs font-semibold",
          muted ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {pct}%
      </span>
    </div>
  );
}

/** A meter's label, carrying the caveat that makes the number readable. */
function MeterLabel({ text, head, hint }: { text: string; head: string; hint: ReactNode }) {
  return (
    <Hint
      content={
        <>
          <HintHead>{head}</HintHead>
          <span>{hint}</span>
        </>
      }
    >
      <span className="border-b border-dotted border-muted-foreground/50 text-xs text-muted-foreground">
        {text}
      </span>
    </Hint>
  );
}

const CONVICTION_HINT = (
  <>
    The model&apos;s own estimate that this call is directionally right over the horizon —
    for a buy, that it beats the NIFTY 50. It is a{" "}
    <b>self-assessment, not a calibrated probability</b>, and has not been scored against
    outcomes.
  </>
);

const EVIDENCE_HINT = (
  <>
    How much of that view rests on real data rather than inference. The desk reads live
    price and the 52-week range only — no earnings, valuation or filings — so this is{" "}
    <b>low by construction</b>. A high conviction on a low evidence base is an opinion,
    not a finding.
  </>
);

/**
 * Conviction and evidence, always together (B11 phase 4).
 *
 * Conviction alone reads as a quality score; next to an evidence bar that is
 * honestly low it reads as what it is — a strong-ish opinion formed on very
 * little data. Never draw one without the other when both exist.
 */
function Meters({ rec }: { rec: AnalystRecommendation }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-1">
        <MeterLabel text="Conviction" head="Analyst · conviction" hint={CONVICTION_HINT} />
        <MeterBar value={rec.confidence} />
      </div>
      {rec.evidence_quality != null ? (
        <div className="flex flex-col gap-1">
          <MeterLabel text="Evidence" head="Analyst · evidence" hint={EVIDENCE_HINT} />
          <MeterBar value={rec.evidence_quality} muted />
        </div>
      ) : null}
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="bg-card px-2.5 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "adp-num mt-0.5 text-sm font-semibold tracking-[-0.01em]",
          value === null && "text-[var(--adp-faint)]",
        )}
      >
        {value ?? "—"}
      </div>
    </div>
  );
}

function Thesis({ side, text }: { side: "bull" | "bear"; text: string }) {
  return (
    <div
      className={cn(
        "border-l-2 pl-3",
        side === "bull" ? "border-[var(--adp-good)]" : "border-[var(--adp-bad)]",
      )}
    >
      <div
        className={cn(
          "text-[11px] font-semibold uppercase tracking-[0.05em]",
          side === "bull" ? "text-[var(--adp-good)]" : "text-[var(--adp-bad)]",
        )}
      >
        {side === "bull" ? "Bull" : "Bear"}
      </div>
      <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--adp-prose)]">{text}</p>
    </div>
  );
}

function Tags({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((it, i) => (
          <span
            key={i}
            className="rounded-full border border-border bg-secondary px-2.5 py-0.5 text-[11.5px] text-muted-foreground"
          >
            {it}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * A candidate that cleared the guardrails — the full brief.
 *
 * Three of these fill a row, which is not a coincidence: the sector cap allows
 * three positions, so a full row is a full sector.
 */
export function RecommendationCard({
  rec,
  risk,
}: {
  rec: AnalystRecommendation;
  risk?: RiskAssessment;
}) {
  return (
    <Card className="flex flex-col gap-3.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0">
          <div className="truncate text-base font-semibold tracking-[-0.01em]">{rec.symbol}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {risk?.sector ?? "Sector not reported"}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">
          <ActionBadge action={rec.action} />
          {risk ? <RiskBadge decision={risk.decision} flags={risk.flags} /> : null}
        </div>
      </div>

      <Meters rec={rec} />

      {/* One hairline grid, so the two figures read as one object. Unknown is
          "—" and never a computed zero (DECISION, null states). */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border">
        <Figure
          label="Target"
          value={rec.target_price != null ? `₹${inr.format(rec.target_price)}` : null}
        />
        <Figure label="Horizon" value={rec.time_horizon ?? null} />
      </div>

      <div className="flex flex-col gap-2.5">
        <Thesis side="bull" text={rec.bull_thesis} />
        <Thesis side="bear" text={rec.bear_thesis} />
      </div>

      <Tags label="Catalysts" items={rec.catalysts} />
      <Tags label="Key risks" items={rec.key_risks} />
      <Tags label="Data gaps" items={rec.data_gaps ?? []} />

      {risk?.notes ? (
        <p className="border-t border-[var(--adp-hairline)] pt-2.5 text-xs text-muted-foreground">
          <b className="font-semibold text-foreground">Risk Manager:</b> {risk.notes}
        </p>
      ) : null}
    </Card>
  );
}

/**
 * A candidate the guardrails stopped.
 *
 * Shown, never hidden: a rejection is a result, and the reason is the
 * interesting part — after B11 the rejecting guardrails are `action: avoid` and
 * the sector cap, so a name can be stopped with nothing wrong with its numbers.
 * It gets less room than a cleared call, not less honesty.
 */
export function RejectedCard({
  rec,
  risk,
}: {
  rec: AnalystRecommendation;
  risk?: RiskAssessment;
}) {
  const reason = risk?.notes ?? risk?.violations?.join(" · ") ?? "Rejected by the Risk Manager.";
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold tracking-[-0.01em]">{rec.symbol}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {risk?.sector ?? "Sector not reported"}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">
          <ActionBadge action={rec.action} />
          {risk ? <RiskBadge decision={risk.decision} flags={risk.flags} /> : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
        <span className="adp-num">
          Conviction{" "}
          <b className="font-semibold text-foreground">
            {Math.round(rec.confidence * 100)}%
          </b>
        </span>
        {rec.evidence_quality != null ? (
          <span className="adp-num">
            Evidence <b className="font-semibold">{Math.round(rec.evidence_quality * 100)}%</b>
          </span>
        ) : null}
        <span>
          {rec.target_price != null ? `Target ₹${inr.format(rec.target_price)}` : "No target issued"}
        </span>
      </div>

      <p className="text-xs text-muted-foreground">{reason}</p>
    </Card>
  );
}
