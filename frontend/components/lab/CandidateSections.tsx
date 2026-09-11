import type { ReactNode } from "react";

import { RecommendationCard, RejectedCard } from "@/components/lab/RecommendationCard";
import { EmptyCallout } from "@/components/ui/adp";
import type { AnalystRecommendation, RiskAssessment } from "@/lib/api";

/** A section rule with a heading and a one-line gloss (`lab/a-console.html`). */
function SectionHead({ title, hint }: { title: string; hint: ReactNode }) {
  return (
    <div className="mt-8 mb-3.5 flex items-baseline gap-2.5">
      <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h2>
      <span className="text-[12.5px] text-muted-foreground">{hint}</span>
      <span className="relative -top-0.5 flex-1 border-t border-border" aria-hidden />
    </div>
  );
}

/**
 * The run's candidates, split by outcome.
 *
 * Splitting them is the design decision, not a layout convenience: mixing a
 * rejection into a grid of cleared calls asks the reader to re-derive the
 * verdict from a badge on every card. Cleared names get the full brief three to
 * a row — three is the sector cap, so a full row is a full sector — and
 * rejections get a compact card that leads with the reason.
 */
export function CandidateSections({
  recs,
  risks,
}: {
  recs: AnalystRecommendation[];
  risks: Record<string, RiskAssessment>;
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
            hint={
              cleared.length === 1
                ? "One call, awaiting your sign-off"
                : `${cleared.length}, in the order the sector slots filled`
            }
          />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {cleared.map(({ rec, risk }) => (
              <RecommendationCard key={rec.symbol} rec={rec} risk={risk} />
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
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {stopped.map(({ rec, risk }) => (
              <RejectedCard key={rec.symbol} rec={rec} risk={risk} />
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}
