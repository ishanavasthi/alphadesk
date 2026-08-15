import type { Metadata } from "next";
import type { ReactNode } from "react";
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
 * shadcn utility inside this tree resolves to the zinc light palette while the
 * legacy terminal pages keep theirs. `min-h-screen` matters — the root `<body>`
 * is still painted in the terminal's near-black, and this wrapper is what covers
 * it.
 */
export default function PortfolioLayout({ children }: { children: ReactNode }) {
  return (
    <div data-adp className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-[1120px] px-4 pb-16 sm:px-6">{children}</div>
    </div>
  );
}
