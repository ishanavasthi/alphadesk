"use client";

import { useState } from "react";
import { Star, X, Loader2, RefreshCw } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { getWatchlist, removeFromWatchlist, type WatchlistItem } from "@/lib/api";

export function WatchlistButton() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await getWatchlist());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function onOpenChange(o: boolean) {
    setOpen(o);
    if (o) load();
  }

  async function remove(symbol: string) {
    try {
      await removeFromWatchlist(symbol);
      setItems((xs) => xs.filter((x) => x.symbol !== symbol));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <button
        onClick={() => onOpenChange(true)}
        className="flex items-center gap-1.5 rounded-sm border border-border bg-secondary/40 px-2 py-1 font-mono text-[0.65rem] uppercase tracking-[0.1em] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
      >
        <Star className="h-3 w-3" />
        Watchlist
      </button>

      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <div className="flex items-center gap-2 text-primary">
              <Star className="h-4 w-4" />
              <span className="eyebrow text-primary">Paper watchlist</span>
            </div>
            <DialogTitle>
              {items.length} stock{items.length === 1 ? "" : "s"}
            </DialogTitle>
            <DialogDescription>
              Stocks you approved into the AlphaDesk paper watchlist. Not connected to
              any brokerage.
            </DialogDescription>
          </DialogHeader>

          <div className="max-h-72 space-y-1.5 overflow-y-auto">
            {loading && <div className="eyebrow caret">Loading</div>}
            {error && <p className="font-mono text-xs text-down">{error}</p>}
            {!loading && !error && items.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Nothing here yet. Approve stocks from a run to add them.
              </p>
            )}
            {items.map((it) => (
              <div
                key={it.symbol}
                className="flex items-center justify-between gap-3 border border-border bg-card px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="font-mono text-sm font-bold text-primary">{it.symbol}</div>
                  {it.query && <div className="truncate eyebrow">{it.query}</div>}
                </div>
                <div className="flex items-center gap-2.5">
                  {it.added_at && (
                    <span className="font-mono text-[0.62rem] text-muted-foreground">
                      {new Date(it.added_at).toLocaleDateString()}
                    </span>
                  )}
                  <button
                    onClick={() => remove(it.symbol)}
                    className="text-muted-foreground transition-colors hover:text-down"
                    aria-label={`Remove ${it.symbol}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="flex justify-end">
            <Button variant="outline" size="sm" onClick={load} disabled={loading}>
              {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              Refresh
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
