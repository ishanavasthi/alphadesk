import Link from "next/link";
import { Github } from "lucide-react";
import { AuthButton } from "@/components/AuthButton";
import { AppNav } from "@/components/shell/AppNav";
import { UserMenu } from "@/components/UserMenu";
import { WatchlistButton } from "@/components/WatchlistButton";
import { AUTH_ENABLED } from "@/lib/auth";

/** The product surfaces, in the order they are offered everywhere. */
const NAV_LINKS = [
  { href: "/portfolio", label: "Portfolio" },
  { href: "/lab", label: "Lab" },
];

export function TopBar() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-6xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-baseline gap-2.5">
          {/* Home is the dashboard when there is an account behind it; with the
              flag off the Lab is the whole app, so the wordmark stays here. */}
          <Link
            href={AUTH_ENABLED ? "/portfolio" : "/lab"}
            className="font-mono text-sm font-bold tracking-[0.18em] text-primary"
          >
            ALPHADESK
          </Link>
          <span className="hidden eyebrow sm:inline">NSE Research Terminal</span>
          <AppNav
            links={NAV_LINKS}
            className="ml-2 font-mono text-xs uppercase tracking-wider"
          />
        </div>
        <div className="flex items-center gap-3">
          {/* Two different questions, side by side: `UserMenu` is "who are
              you" (Clerk, flag-gated — renders and downloads nothing when the
              flag is off), `AuthButton` is "is a broker linked". */}
          <UserMenu />
          <AuthButton />
          <WatchlistButton />
          <a
            href="https://github.com/ishanavasthi/alphadesk"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Source code on GitHub"
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            <Github className="h-4 w-4" />
          </a>
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-up animate-pulse-ring" />
            <span className="eyebrow text-up">Live</span>
          </div>
        </div>
      </div>
    </header>
  );
}
