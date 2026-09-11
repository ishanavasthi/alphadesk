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
import { Badge, Button } from "@/components/ui/adp";
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
      <Button variant="outline" size="sm" onClick={() => onOpenChange(true)}>
        <Star className="h-3.5 w-3.5" />
        Watchlist
      </Button>

      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <Badge variant="lab" className="self-start">
              Paper watchlist
            </Badge>
            <DialogTitle className="mt-2">
              {items.length} stock{items.length === 1 ? "" : "s"}
            </DialogTitle>
            <DialogDescription>
              Stocks you approved into the AlphaDesk paper watchlist. Not connected to
              any brokerage.
            </DialogDescription>
          </DialogHeader>

          <div className="max-h-72 space-y-1.5 overflow-y-auto">
            {loading && <div className="text-xs text-muted-foreground">Loading…</div>}
            {error && <p className="text-xs text-[var(--adp-bad)]">{error}</p>}
            {!loading && !error && items.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Nothing here yet. Approve stocks from a run to add them.
              </p>
            )}
            {items.map((it) => (
              <div
                key={it.symbol}
                className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold">{it.symbol}</div>
                  {it.query && (
                    <div className="truncate text-xs text-muted-foreground">{it.query}</div>
                  )}
                </div>
                <div className="flex items-center gap-2.5">
                  {it.added_at && (
                    <span className="adp-num text-xs text-[var(--adp-faint)]">
                      {new Date(it.added_at).toLocaleDateString()}
                    </span>
                  )}
                  <button
                    onClick={() => remove(it.symbol)}
                    className="text-muted-foreground transition-colors hover:text-[var(--adp-bad)]"
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
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Refresh
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
