import { WatchlistButton } from "@/components/WatchlistButton";

export function TopBar() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-6xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-baseline gap-2.5">
          <span className="font-mono text-sm font-bold tracking-[0.18em] text-primary">
            ALPHADESK
          </span>
          <span className="hidden eyebrow sm:inline">NSE Research Terminal</span>
        </div>
        <div className="flex items-center gap-3">
          <WatchlistButton />
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-up animate-pulse-ring" />
            <span className="eyebrow text-up">Live</span>
          </div>
        </div>
      </div>
    </header>
  );
}
