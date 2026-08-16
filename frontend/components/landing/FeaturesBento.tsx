import { BarChart3, Network, Search, TrendingUp } from "lucide-react";

import { BentoCard, IconTile, MetricChip, SectionHead, StageArrow, StageChip } from "./primitives";

const OVERVIEW_AGENTS = [
  "Allocation critic",
  "Concentration risk",
  "SIP health",
  "Performance attribution",
];

export function FeaturesBento() {
  return (
    <section id="features" aria-labelledby="features-h" className="py-14 sm:py-[72px]">
      <SectionHead
        id="features-h"
        kicker="Features"
        title="The dashboard is the product"
        sub="Computed numbers first. Narrative second. Nothing rendered that was not verified."
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-6">
        <BentoCard>
          <IconTile>
            <BarChart3 className="h-[18px] w-[18px]" aria-hidden />
          </IconTile>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">Net-worth dashboard</h3>
          <p className="text-[13.5px] text-muted-foreground">
            Invested vs current, absolute and percent. Allocation by asset type, sector and
            market cap. A sortable holdings table with honest nulls: an unknown cost basis
            renders <MetricChip>&mdash;</MetricChip>, never a fake -100%.
          </p>
        </BentoCard>

        <BentoCard>
          <IconTile>
            <TrendingUp className="h-[18px] w-[18px]" aria-hidden />
          </IconTile>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
            Daily history you can trust
          </h3>
          <p className="text-[13.5px] text-muted-foreground">
            One snapshot a day, <b className="font-semibold text-foreground">net worth at Indian
            market close, all sources settled</b>, captured <MetricChip>~23:45 IST</MetricChip>{" "}
            after mutual-fund NAVs publish. A missed snapshot can never be backfilled, so
            staleness is shown, not hidden: “History paused, last captured N days ago.”
          </p>
        </BentoCard>

        <BentoCard>
          <IconTile>
            <Network className="h-[18px] w-[18px]" aria-hidden />
          </IconTile>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
            An AI overview that shows its work
          </h3>
          <p className="text-[13.5px] text-muted-foreground">
            Every metric is computed in Python; the agents may not invent figures, and every
            claim carries its number.{" "}
            <em>
              You are <MetricChip>47%</MetricChip> financials. HHI <MetricChip>0.31</MetricChip>.
              Your largest holding is <MetricChip>22%</MetricChip> of net worth
            </em>{" "}
            (illustrative). If the LLM is down, “AI overview unavailable”, and every number
            still renders.
          </p>
          <div className="mt-0.5 flex flex-wrap gap-1.5" aria-label="Overview agents">
            {OVERVIEW_AGENTS.map((agent) => (
              <StageChip key={agent}>{agent}</StageChip>
            ))}
            <StageArrow />
            <StageChip>Synthesizer</StageChip>
          </div>
        </BentoCard>

        <BentoCard>
          <IconTile>
            <Search className="h-[18px] w-[18px]" aria-hidden />
          </IconTile>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
            See it before you sign in
          </h3>
          <p className="text-[13.5px] text-muted-foreground">
            A public <MetricChip>/demo</MetricChip> renders the full dashboard from sample data.
            No sign-in, no broker link, and an unmissable banner on every screen, so a
            screenshot can never pass for real money.
          </p>
        </BentoCard>
      </div>
    </section>
  );
}
