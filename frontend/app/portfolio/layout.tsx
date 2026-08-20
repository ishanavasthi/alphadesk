import type { Metadata } from "next";
import type { ReactNode } from "react";

import { PortfolioProvider } from "@/components/portfolio/PortfolioProvider";
import { ThemeBootstrap } from "@/components/shell/ThemeBootstrap";
import { PortfolioShell } from "./PortfolioShell";
import "./portfolio.css";

export const metadata: Metadata = {
  title: "Portfolio — AlphaDesk",
  description:
    "Net worth, allocation and holdings from a linked IND Money account. Descriptive analytics only; not investment advice.",
};

/**
 * The D1 surface's own shell.
 *
 * `data-adp` is what scopes the DECISION token set (see `portfolio.css`): every
 * shadcn utility inside this tree resolves to the zinc palette — light, or its
 * dark variant when `data-adp-theme="dark"` is set below — while the
 * legacy terminal pages keep theirs. `ThemeBootstrap` is what puts that
 * `data-adp-theme="dark"` there, and it owns *both* halves: the inline
 * pre-paint `<script>` for a document load (no flash of the wrong theme), and a
 * mount effect for the case the script cannot cover. This layout used to inline
 * the script itself and stop there, which broke the client-side route change —
 * navigating Portfolio → Lab → Portfolio unmounts this wrapper and mounts a
 * fresh one, and React re-inserting the `<script>` element does *not* re-execute
 * it, so the new `#adp-root` came back bare and a reader who picked dark landed
 * on a light dashboard. `min-h-screen` matters — the root `<body>`
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
    // `id` is how `ThemeBootstrap` and `ThemeToggle` reach this element: both
    // run outside React, before and after hydration respectively.
    <div id="adp-root" data-adp className="min-h-screen bg-background text-foreground">
      <ThemeBootstrap />
      <div className="mx-auto max-w-[1120px] px-4 pb-16 sm:px-6">
        <PortfolioProvider>
          <PortfolioShell>{children}</PortfolioShell>
        </PortfolioProvider>
      </div>
    </div>
  );
}
