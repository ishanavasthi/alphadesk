import type { ReactNode } from "react";

import { RecommendationCard, RejectedCard } from "@/components/lab/RecommendationCard";
import type { RunStatus } from "@/components/lab/RunHeader";
import { EmptyCallout } from "@/components/ui/adp";
import type { AnalystRecommendation, RiskAssessment } from "@/lib/api";

/** A section rule with a heading and a one-line gloss (`lab/a-console.html`). */
function SectionHead({ title, hint }: { title: string; hint: ReactNode }) {
  return (
    <div className="mt-8 mb-3.5 flex items-baseline gap-2.5">
      <h2 className="shrink-0 text-[15px] font-semibold tracking-[-0.01em]">{title}</h2>
      <span className="text-[12.5px] text-muted-foreground">{hint}</span>
      <span className="relative -top-0.5 flex-1 border-t border-border" aria-hidden />
    </div>
  );
}

/**
 * Columns for `count` cards. A fixed three-up grid left a lone card in a third
 * of the row and two thirds of nothing beside it; the row is only divided as
 * far as there are cards to fill it.
 */
function gridCols(count: number): string {
  if (count >= 3) return "md:grid-cols-2 lg:grid-cols-3";
  if (count === 2) return "md:grid-cols-2";
  return "";
}

/** Where the cleared calls stand, so the hint stops asking for a sign-off already given. */
function clearedHint(count: number, status: RunStatus | undefined): string {
  const lead = count === 1 ? "One call" : `${count}, in the order the sector slots filled`;
  switch (status) {
    case "awaiting_approval":
      return `${lead}, awaiting your sign-off`;
    case "completed":
      return `${lead}, signed off`;
    case "rejected":
      return `${lead}, declined at sign-off`;
    default:
      return lead;
  }
}

/**
 * The run's candidates, split by outcome.
 *
 * Splitting them is the design decision, not a layout convenience: mixing a
 * rejection into a grid of cleared calls asks the reader to re-derive the
 * verdict from a badge on every card. Cleared names get the full brief, up to
 * three to a row — three is the sector cap, so a full row is a full sector — and
 * rejections get a compact card that leads with the reason.
 */
export function CandidateSections({
  recs,
  risks,
  status,
}: {
  recs: AnalystRecommendation[];
  risks: Record<string, RiskAssessment>;
  status?: RunStatus;
}) {
  const items = recs.map((rec) => ({ rec, risk: risks[rec.symbol] }));
  const cleared = items.filter((x) => x.risk?.approved === true);
  // A call with no assessment at all is not "cleared" — the Risk Manager is the
  // only thing that clears anything — so it belongs with the ones that did not.
  const stopped = items.filter((x) => x.risk?.approved !== true);

  if (!items.length) {
    return (
      <EmptyCallout className="mt-6">
        <b className="font-semibold text-foreground">No candidates in this run.</b> The scan
        returned nothing that matched, so the Analyst had nothing to write up.
      </EmptyCallout>
    );
  }

  return (
    <>
      {cleared.length > 0 ? (
        <section>
          <SectionHead
            title="Cleared the guardrails"
            hint={clearedHint(cleared.length, status)}
          />
          <div className={`grid grid-cols-1 gap-4 ${gridCols(cleared.length)}`}>
            {cleared.map(({ rec, risk }) => (
              <RecommendationCard
                key={rec.symbol}
                rec={rec}
                risk={risk}
                wide={cleared.length === 1}
              />
            ))}
          </div>
        </section>
      ) : null}

      {stopped.length > 0 ? (
        <section>
          <SectionHead
            title="Not staged"
            hint={
              stopped.length === 1
                ? "The one the guardrails stopped — shown, never hidden"
                : `The ${stopped.length} the guardrails stopped — shown, never hidden`
            }
          />
          <div className={`grid grid-cols-1 gap-4 ${gridCols(stopped.length)}`}>
            {stopped.map(({ rec, risk }) => (
              <RejectedCard key={rec.symbol} rec={rec} risk={risk} />
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}
