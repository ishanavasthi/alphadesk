import Link from "next/link";
import { Github } from "lucide-react";

import { ThemeToggle } from "@/components/portfolio/ThemeToggle";

/**
 * The marketing footer.
 *
 * `PortfolioFooter` carries the disclaimer and the legal links but no source
 * link, and the marketing pages are where the open-source repo is worth naming,
 * so this surface gets its own footer rather than an extra prop on a shared one.
 *
 * It also hosts the theme toggle. The dashboard mounts the same component in its
 * top bar; both write `localStorage["adp-theme"]` and flip the attribute on the
 * `#adp-root` wrapper, so there is one theme mechanism and one stored choice
 * across the whole product.
 */
export function MarketingFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-[1120px] flex-wrap items-center gap-x-6 gap-y-3 px-4 pb-10 pt-7 text-[12.5px] text-[var(--adp-faint)] sm:px-6">
        <span className="h-2 w-2 flex-none rounded-[3px] bg-[var(--adp-accent)]" aria-hidden />
        <span>descriptive analytics only · not investment advice</span>
        <span className="hidden flex-1 sm:block" />
        <a
          href="https://github.com/ishanavasthi/alphadesk"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-muted-foreground transition-colors hover:text-foreground"
        >
          <Github className="h-3.5 w-3.5" aria-hidden />
          Open source
        </a>
        <Link href="/privacy" className="text-muted-foreground transition-colors hover:text-foreground">
          Privacy
        </Link>
        <Link href="/terms" className="text-muted-foreground transition-colors hover:text-foreground">
          Terms
        </Link>
        <ThemeToggle />
      </div>
    </footer>
  );
}
