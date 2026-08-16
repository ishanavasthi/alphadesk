import type { Metadata } from "next";
import type { ReactNode } from "react";

import { PortfolioProvider } from "@/components/portfolio/PortfolioProvider";
import { PortfolioShell } from "./PortfolioShell";
import "./portfolio.css";

export const metadata: Metadata = {
  title: "Portfolio — AlphaDesk",
  description:
    "Net worth, allocation and holdings from a linked IND Money account. Descriptive analytics only; not investment advice.",
};

/**
 * Theme bootstrap, inlined so it runs before the first paint.
 *
 * It sits *inside* the wrapper, as its first child: at that point the parser has
 * already created the element, so `getElementById` finds it and the attribute is
 * set while the rest of the tree is still being parsed — no flash of the wrong
 * theme, and nothing to hydrate. A stored choice wins; its absence follows the
 * OS. Failures are swallowed on purpose: a browser that refuses `localStorage`
 * (private mode, blocked storage) should render the light surface, not a blank
 * page.
 */
const THEME_BOOTSTRAP = `(function(){try{var r=document.getElementById("adp-root");if(!r)return;var s=localStorage.getItem("adp-theme");if(s==="dark"||(s!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches))r.setAttribute("data-adp-theme","dark")}catch(e){}})()`;

/**
 * The D1 surface's own shell.
 *
 * `data-adp` is what scopes the DECISION token set (see `portfolio.css`): every
 * shadcn utility inside this tree resolves to the zinc palette — light, or its
 * dark variant when `data-adp-theme="dark"` is set below — while the
 * legacy terminal pages keep theirs. `min-h-screen` matters — the root `<body>`
 * is still painted in the terminal's near-black, and this wrapper is what covers
 * it.
 *
 * It is also where the dashboard's one load lives. `PortfolioProvider` fetches
 * the snapshot, history and holdings, and the App Router keeps this layout
 * mounted while its children (Overview / Holdings / Performance) swap — so the
 * tabs are free, and the gates (locked, unauthorized, connect, source error)
 * render here in place of the whole surface whichever URL was hit first.
 */
export default function PortfolioLayout({ children }: { children: ReactNode }) {
  return (
    // `id` is how the bootstrap below and `ThemeToggle` reach this element:
    // both run outside React, before and after hydration respectively.
    <div id="adp-root" data-adp className="min-h-screen bg-background text-foreground">
      <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      <div className="mx-auto max-w-[1120px] px-4 pb-16 sm:px-6">
        <PortfolioProvider>
          <PortfolioShell>{children}</PortfolioShell>
        </PortfolioProvider>
      </div>
    </div>
  );
}
