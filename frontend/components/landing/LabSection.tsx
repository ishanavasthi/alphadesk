import { CircleAlert, ListChecks } from "lucide-react";

import { BentoCard, IconTile, MetricChip, SectionHead, StageArrow, StageChip } from "./primitives";

export function LabSection() {
  return (
    <section id="lab" aria-labelledby="lab-h" className="py-14 sm:py-[72px]">
      <SectionHead
        id="lab-h"
        kicker="Lab · simulation"
        title="The research desk lives in the Lab"
        sub="The multi-agent desk is still here, clearly labelled a simulation, and never fused with your real portfolio view."
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-6">
        <BentoCard>
          <IconTile>
            <ListChecks className="h-[18px] w-[18px]" aria-hidden />
          </IconTile>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
            Scanner to watchlist, on paper
          </h3>
          <p className="text-[13.5px] text-muted-foreground">
            A pipeline scans NSE movers, researches candidates, writes analyst reports, applies
            risk guardrails, then pauses. Nothing joins the watchlist until you approve it.
          </p>
          <div className="mt-0.5 flex flex-wrap gap-1.5" aria-label="Lab pipeline stages">
            <StageChip>Scanner</StageChip>
            <StageArrow />
            <StageChip>Research</StageChip>
            <StageArrow />
            <StageChip>Analyst</StageChip>
            <StageArrow />
            <StageChip>Risk guardrails</StageChip>
            <StageArrow />
            <StageChip tone="warn">⏸ You</StageChip>
            <StageArrow />
            <StageChip>Paper watchlist</StageChip>
          </div>
        </BentoCard>

        <BentoCard>
          <IconTile>
            <CircleAlert className="h-[18px] w-[18px]" aria-hidden />
          </IconTile>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">
            A simulation that says so
          </h3>
          <p className="text-[13.5px] text-muted-foreground">
            Every Lab view carries a “simulation, not investment advice” label. Its picks land on
            a paper watchlist only, they are never shown beside your real holdings, and{" "}
            <MetricChip>0</MetricChip> real orders are ever placed. The Lab has no way to trade.
          </p>
        </BentoCard>
      </div>
    </section>
  );
}
