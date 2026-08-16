import type { Metadata } from "next";
import type { ReactNode } from "react";

// The DECISION token set (the light shadcn palette), scoped to `[data-adp]`.
// Shared with `/portfolio` and the marketing group; imported here so the demo
// route carries it too.
import "../portfolio/portfolio.css";
import { DemoBanner } from "@/components/shell/DemoBanner";
import { ThemeBootstrap } from "@/components/shell/ThemeBootstrap";

export const metadata: Metadata = {
  title: "Live demo — AlphaDesk",
  description:
    "A fully-rendered AlphaDesk portfolio dashboard on invented sample data. No sign-in, no account, nothing real.",
  robots: { index: true, follow: true },
};

/**
 * The public `/demo` shell.
 *
 * `data-adp` scopes the shadcn palette (as `/portfolio` does) and `id="adp-root"`
 * with `ThemeBootstrap` is what reads the reader's stored light/dark choice —
 * without them this surface had the dark half of the token set compiled in and
 * no way to ask for it, so it rendered light for everyone. There is no toggle
 * here: `/demo` inherits the choice made on the marketing header or the
 * dashboard, which is the same one choice the rest of the product shares.
 *
 * The sticky `DemoBanner` keeps the sample-data disclaimer on screen at every
 * scroll position. The route itself makes no LLM or authenticated call — see
 * `components/shell/DemoDashboard.tsx`.
 */
export default function DemoLayout({ children }: { children: ReactNode }) {
  return (
    <div id="adp-root" data-adp className="min-h-screen bg-background text-foreground">
      <ThemeBootstrap />
      <DemoBanner />
      <main className="mx-auto max-w-[1120px] px-4 pb-16 pt-6 sm:px-6">{children}</main>
    </div>
  );
}
