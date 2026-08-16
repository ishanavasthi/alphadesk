import type { ReactNode } from "react";

// The DECISION token set (light shadcn palette plus its dark variant), scoped
// to `[data-adp]`.
import "../portfolio/portfolio.css";
import { SiteHeader } from "@/components/shell/SiteHeader";
import { MarketingFooter } from "@/components/landing/MarketingFooter";

/**
 * Theme bootstrap, inlined so it runs before the first paint.
 *
 * Byte-identical to the dashboard's (`app/portfolio/layout.tsx`): same storage
 * key, same wrapper id, same rule that a stored choice wins and its absence
 * follows the OS. Marketing and dashboard therefore share one theme, so a
 * reader who picked dark on `/portfolio` lands on a dark landing page.
 */
const THEME_BOOTSTRAP = `(function(){try{var r=document.getElementById("adp-root");if(!r)return;var s=localStorage.getItem("adp-theme");if(s==="dark"||(s!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches))r.setAttribute("data-adp-theme","dark")}catch(e){}})()`;

/**
 * The marketing group's shell: landing (`/`), `/privacy`, `/terms`.
 *
 * The shadcn chrome for the product surfaces: the `SiteHeader` and the
 * marketing footer (disclaimers, source link, Privacy/Terms, theme toggle) on
 * every page. `data-adp` scopes the token set exactly as `/portfolio` and
 * `/demo` do, and `id="adp-root"` is what the bootstrap above and `ThemeToggle`
 * reach for; `min-h-screen bg-background` covers the root body's terminal
 * near-black.
 */
export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div
      id="adp-root"
      data-adp
      className="flex min-h-screen flex-col bg-background text-foreground"
    >
      <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      <SiteHeader />
      <div className="flex-1">{children}</div>
      <MarketingFooter />
    </div>
  );
}
