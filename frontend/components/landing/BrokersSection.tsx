import { ExternalLink, Link2 } from "lucide-react";

import { Badge } from "@/components/portfolio/ui";

import { IconTile, SectionHead } from "./primitives";

export function BrokersSection() {
  return (
    <section id="brokers" aria-labelledby="brokers-h" className="py-14 sm:py-[72px]">
      <SectionHead
        id="brokers-h"
        kicker="Brokers"
        title="One source today, read-only"
        sub="AlphaDesk reads holdings through IND Money, which already aggregates Indian stocks, mutual funds, deposits and US stocks in one place."
      />
      <div className="grid max-w-[760px] gap-4 sm:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-2.5 rounded-lg border border-border bg-card p-6 shadow-[0_1px_2px_var(--adp-shadow)]">
          <IconTile>
            <Link2 className="h-[18px] w-[18px]" aria-hidden />
          </IconTile>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">IND Money</h3>
          <p className="text-[13.5px] text-muted-foreground">
            The supported source today. A standard OAuth link with read scope only, revocable
            from AlphaDesk or from IND Money at any time.
          </p>
          <p className="text-[13.5px] text-muted-foreground">
            Don&rsquo;t have an IND Money account?{" "}
            <a
              href="https://www.indmoney.com"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-medium text-[var(--adp-accent)] hover:underline"
            >
              indmoney.com
              <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          </p>
        </div>

        <div className="flex min-w-0 flex-col gap-2.5 rounded-lg border border-dashed border-border bg-card p-6">
          <Badge variant="soon" className="self-start">
            SOON
          </Badge>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">More brokers coming soon</h3>
          <p className="text-[13.5px] text-muted-foreground">
            Additional read-only sources are planned. Until one ships it is listed here as
            pending, never implied on the dashboard.
          </p>
        </div>
      </div>
    </section>
  );
}
