import type { ReactNode } from "react";

// The DECISION token set (light shadcn palette), scoped to `[data-adp]` — the
// footer's colours are defined here, exactly as the marketing and portfolio
// shells pull it in.
import "../../app/portfolio/portfolio.css";
import { PortfolioFooter } from "@/components/portfolio/ui";

/**
 * Wraps a bare auth route (`/sign-in`, `/waitlist`) so the site footer — and the
 * Privacy/Terms links it carries — is reachable there too.
 *
 * These two routes sit **outside** the marketing group that renders the footer
 * on every other public page, yet one of them (`/waitlist`) collects an email.
 * A page that asks for a person's data with no route to the privacy policy is
 * the exact gap this closes. `data-adp` scopes the light palette the footer's
 * tokens need and matches Clerk's default (light) form theme, so the card and
 * the page read as one surface.
 */
export function AuthFooterShell({ children }: { children: ReactNode }) {
  return (
    <div data-adp className="flex min-h-screen flex-col bg-background text-foreground">
      <div className="flex-1">{children}</div>
      <div className="mx-auto w-full max-w-[1120px] px-4 pb-10 sm:px-6">
        <PortfolioFooter demo={false} />
      </div>
    </div>
  );
}
