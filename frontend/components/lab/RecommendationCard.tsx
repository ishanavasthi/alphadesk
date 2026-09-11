import { ActionBadge, RiskBadge } from "@/components/lab/StatusBadge";
import { Card } from "@/components/ui/adp";
import { cn } from "@/lib/utils";
import type { AnalystRecommendation, RiskAssessment } from "@/lib/api";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/** The two lines `backend/agents/risk_manager.py` actually enforces. */
const FLOOR = 0.7;
const PASS = 0.75;

/**
 * Analyst confidence, drawn against the guardrails rather than on its own.
 *
 * 0.82 and 0.68 are the same bar without the ticks — and the difference between
 * them is the whole verdict. The fill's tone says which side of the floor the
 * call landed on; the ticks say where the floor is. Colour is status here, not
 * series (DECISION chart rules), so the three tones are the three outcomes.
 */
function ConfidenceMeter({ value, tone }: { value: number; tone: "accent" | "warn" | "bad" }) {
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-muted-foreground">Analyst confidence</span>
        <span className="adp-num text-[13px] font-semibold">{clamped.toFixed(2)}</span>
      </div>
      <div className="adp-meter mt-1.5">
        <div
          className="adp-meter-fill"
          data-tone={tone === "accent" ? undefined : tone}
          style={{ width: `${clamped * 100}%` }}
        />
        <span className="adp-meter-tick" style={{ left: `${FLOOR * 100}%` }} aria-hidden />
        <span className="adp-meter-tick" style={{ left: `${PASS * 100}%` }} aria-hidden />
      </div>
      <div className="adp-num mt-1 flex justify-between text-[10.5px] text-[var(--adp-faint)]">
        <span>0.00</span>
        <span>floor 0.70 · pass 0.75</span>
        <span>1.00</span>
      </div>
    </div>
  );
}

/** Which side of the guardrails a call landed on, as a meter tone. */
function toneFor(rec: AnalystRecommendation, risk?: RiskAssessment): "accent" | "warn" | "bad" {
  if (rec.confidence < FLOOR) return "bad";
  if (risk?.decision === "FLAG") return "warn";
  return "accent";
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
 * three positions, so a full row *is* a full sector.
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
          {risk ? <RiskBadge decision={risk.decision} /> : null}
        </div>
      </div>

      <ConfidenceMeter value={rec.confidence} tone={toneFor(rec, risk)} />

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
 * interesting part — a name can outscore two that cleared and still be stopped
 * by the sector cap. It gets less room than a cleared call, not less honesty,
 * so the thesis is dropped and the violations are not.
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
          {risk ? <RiskBadge decision={risk.decision} /> : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 text-xs text-muted-foreground">
        <span>Confidence</span>
        <span className="adp-meter min-w-[5rem] flex-1">
          <span
            className="adp-meter-fill"
            data-tone={rec.confidence < FLOOR ? "bad" : undefined}
            style={{ width: `${Math.max(0, Math.min(1, rec.confidence)) * 100}%` }}
          />
          <span className="adp-meter-tick" style={{ left: `${FLOOR * 100}%` }} aria-hidden />
        </span>
        <b className="adp-num text-[13px] font-semibold text-foreground">
          {rec.confidence.toFixed(2)}
        </b>
        <span>
          {rec.target_price != null ? `Target ₹${inr.format(rec.target_price)}` : "No target issued"}
        </span>
      </div>

      <p className="text-xs text-muted-foreground">{reason}</p>
    </Card>
  );
}
