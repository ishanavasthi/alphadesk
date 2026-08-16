import type { ReactNode } from "react";

// The DECISION token set (light shadcn palette), scoped to `[data-adp]`.
import "../portfolio/portfolio.css";
import { SiteHeader } from "@/components/shell/SiteHeader";
import { PortfolioFooter } from "@/components/portfolio/ui";

/**
 * The marketing group's shell — landing (`/`), `/privacy`, `/terms`.
 *
 * The shadcn chrome for the product surfaces: the light `SiteHeader` and the
 * shared footer (with its Privacy/Terms links) on every page. `data-adp` scopes
 * the light palette, exactly as `/portfolio` and `/demo` do; `min-h-screen
 * bg-background` covers the root body's terminal near-black.
 */
export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div data-adp className="flex min-h-screen flex-col bg-background text-foreground">
      <SiteHeader />
      <div className="flex-1">{children}</div>
      <div className="mx-auto w-full max-w-[1120px] px-4 pb-10 sm:px-6">
        <PortfolioFooter demo={false} />
      </div>
    </div>
  );
}
