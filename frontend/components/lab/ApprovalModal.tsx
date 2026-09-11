"use client";

import { useState } from "react";
import { Check, Loader2, X } from "lucide-react";

import { Hint, HintHead } from "@/components/lab/Hint";
import { ActionBadge, RiskBadge } from "@/components/lab/StatusBadge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge, Button } from "@/components/ui/adp";
import {
  approve,
  type AnalystRecommendation,
  type ApproveResult,
  type RiskAssessment,
} from "@/lib/api";

interface ApprovalModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  actionId: string | null;
  items: { rec: AnalystRecommendation; risk?: RiskAssessment }[];
  onResolved: (approved: boolean, result: ApproveResult) => void;
}

/**
 * The human gate (`docs/design/lab/a-console.html`, "Approval gate").
 *
 * The last sentence before anything is written is the one that has to be exact:
 * this stages names into a *paper* watchlist, and the broker layer is a stub. It
 * says so here rather than only in the banner behind it, because this is the
 * dialog somebody clicks through.
 */
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
          <Badge variant="warn" className="self-start">
            Human approval required
          </Badge>
          <DialogTitle className="mt-2">
            Add {items.length} stock{items.length === 1 ? "" : "s"} to the paper watchlist?
          </DialogTitle>
          <DialogDescription>
            These cleared the risk guardrails. Approving stages them into your paper watchlist — no
            real order is placed, and these names never appear beside your holdings.
          </DialogDescription>
        </DialogHeader>

        <ul className="flex max-h-64 flex-col gap-1.5 overflow-y-auto">
          {items.map(({ rec, risk }) => (
            <li
              key={rec.symbol}
              className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-md border border-border px-3 py-2 text-[13px]"
            >
              <span className="font-semibold">{rec.symbol}</span>
              {risk?.sector ? (
                <span className="text-xs text-muted-foreground">{risk.sector}</span>
              ) : null}
              <span className="flex-1" />
              {/* Conviction and evidence together, as on the card (B11): the
                  first number alone reads as a quality score it is not. */}
              <Hint
                content={
                  <>
                    <HintHead>Conviction · evidence</HintHead>
                    <span>
                      The model&apos;s own confidence that this call is directionally
                      right, then how much real data it rested on. Both are
                      self-assessments; neither is calibrated against outcomes.
                    </span>
                  </>
                }
              >
                <span className="adp-num text-xs text-muted-foreground">
                  {Math.round(rec.confidence * 100)}%
                  {rec.evidence_quality != null ? (
                    <span className="text-[var(--adp-faint)]">
                      {" · "}
                      {Math.round(rec.evidence_quality * 100)}% ev
                    </span>
                  ) : null}
                </span>
              </Hint>
              <ActionBadge action={rec.action} />
              {risk ? <RiskBadge decision={risk.decision} flags={risk.flags} /> : null}
            </li>
          ))}
        </ul>

        {error ? <p className="text-xs text-[var(--adp-bad)]">{error}</p> : null}

        <DialogFooter>
          <Button variant="destructive" onClick={() => decide(false)} disabled={busy !== null}>
            {busy === "reject" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <X className="h-3.5 w-3.5" />
            )}
            Reject run
          </Button>
          <Button variant="primary" onClick={() => decide(true)} disabled={busy !== null}>
            {busy === "approve" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            Approve {items.length}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
