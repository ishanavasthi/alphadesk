import type { ReactNode } from "react";

// The DECISION token set (light shadcn palette plus its dark variant), scoped
// to `[data-adp]`.
import "../portfolio/portfolio.css";
import { SiteHeader } from "@/components/shell/SiteHeader";
import { ThemeBootstrap } from "@/components/shell/ThemeBootstrap";
import { MarketingFooter } from "@/components/landing/MarketingFooter";

/**
 * The marketing group's shell: landing (`/`), `/privacy`, `/terms`.
 *
 * The shadcn chrome for the product surfaces: the `SiteHeader` (which carries
 * the theme toggle) and the marketing footer (disclaimers, source link,
 * Privacy/Terms) on every page. `data-adp` scopes the token set as `/portfolio`
 * and `/demo` do, and `id="adp-root"` is what `ThemeBootstrap` and
 * `ThemeToggle` reach for; `min-h-screen bg-background` covers the root body's terminal
 * near-black.
 */
export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div
      id="adp-root"
      data-adp
      className="flex min-h-screen flex-col bg-background text-foreground"
    >
      <ThemeBootstrap />
      <SiteHeader />
      <div className="flex-1">{children}</div>
      <MarketingFooter />
    </div>
  );
}
