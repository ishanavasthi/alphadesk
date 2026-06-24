"use client";

import { useState } from "react";
import { Check, X, ShieldCheck, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ActionBadge, RiskBadge } from "@/components/StatusBadge";
import { approve, type AnalystRecommendation, type ApproveResult, type RiskAssessment } from "@/lib/api";

interface ApprovalModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  actionId: string | null;
  items: { rec: AnalystRecommendation; risk?: RiskAssessment }[];
  onResolved: (approved: boolean, result: ApproveResult) => void;
}

export function ApprovalModal({
  open,
  onOpenChange,
  actionId,
  items,
  onResolved,
}: ApprovalModalProps) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(approved: boolean) {
    if (!actionId) return;
    setBusy(approved ? "approve" : "reject");
    setError(null);
    try {
      const result = await approve(actionId, approved);
      onResolved(approved, result);
      onOpenChange(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent>
        <DialogHeader>
          <div className="flex items-center gap-2 text-flag">
            <ShieldCheck className="h-4 w-4" />
            <span className="eyebrow text-flag">Human approval required</span>
          </div>
          <DialogTitle>Add {items.length} stock{items.length === 1 ? "" : "s"} to the paper watchlist?</DialogTitle>
          <DialogDescription>
            These cleared the risk guardrails. Approving stages them into the paper
            watchlist. No real order is placed unless a broker is configured.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-64 space-y-1.5 overflow-y-auto">
          {items.map(({ rec, risk }) => (
            <div
              key={rec.symbol}
              className="flex items-center justify-between gap-3 border border-border bg-card px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold text-primary">{rec.symbol}</span>
                {risk?.sector && <span className="eyebrow">{risk.sector}</span>}
              </div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  {Math.round(rec.confidence * 100)}%
                </span>
                <ActionBadge action={rec.action} />
                {risk && <RiskBadge decision={risk.decision} />}
              </div>
            </div>
          ))}
        </div>

        {error && (
          <p className="font-mono text-xs text-down">{error}</p>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => decide(false)}
            disabled={busy !== null}
          >
            {busy === "reject" ? <Loader2 className="animate-spin" /> : <X />}
            Reject
          </Button>
          <Button onClick={() => decide(true)} disabled={busy !== null}>
            {busy === "approve" ? <Loader2 className="animate-spin" /> : <Check />}
            Approve
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
