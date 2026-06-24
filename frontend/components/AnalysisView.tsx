"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft, AlertTriangle, CheckCircle2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { RecommendationCard } from "@/components/RecommendationCard";
import { ApprovalModal } from "@/components/ApprovalModal";
import type { AnalysisPayload, ApproveResult, RiskAssessment } from "@/lib/api";

export function AnalysisView({ payload }: { payload: AnalysisPayload }) {
  const [status, setStatus] = useState(payload.status);
  const [awaiting, setAwaiting] = useState(payload.awaiting_approval);
  const [watchlist, setWatchlist] = useState<string[]>(payload.paper_watchlist ?? []);
  const [rejection, setRejection] = useState(payload.rejection_reason ?? null);
  const [modalOpen, setModalOpen] = useState(false);

  const risks: Record<string, RiskAssessment> = Object.fromEntries(
    (payload.risk_assessments || []).map((r) => [r.symbol, r]),
  );
  const recs = payload.analyst_recommendations || [];
  const passItems = recs
    .map((rec) => ({ rec, risk: risks[rec.symbol] }))
    .filter((x) => x.risk?.approved === true);

  function onResolved(approved: boolean, result: ApproveResult) {
    setAwaiting(false);
    if (approved) {
      setStatus("completed");
      setWatchlist(result.state?.paper_watchlist ?? []);
    } else {
      setStatus("rejected");
      setRejection("Rejected by analyst.");
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
        <div className="min-w-0">
          <div className="font-mono text-sm">
            <span className="text-primary">query{">"}</span>{" "}
            <span className="text-foreground">{payload.query}</span>
          </div>
          <div className="mt-1 flex items-center gap-3 eyebrow">
            <span>RUN {payload.run_id.slice(0, 8)}</span>
            <span className={`pill ${statusPill(status)}`}>{status.replace("_", " ")}</span>
            {payload.created_at && (
              <span>{new Date(payload.created_at).toLocaleString()}</span>
            )}
          </div>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/">
            <ArrowLeft />
            New query
          </Link>
        </Button>
      </div>

      <div className="mt-5 space-y-4">
        {awaiting && (
          <Banner
            tone="flag"
            icon={<ShieldCheck className="h-4 w-4" />}
            title={`${passItems.length} stock${passItems.length === 1 ? "" : "s"} awaiting approval`}
            action={
              <Button size="sm" onClick={() => setModalOpen(true)}>
                Review &amp; approve
              </Button>
            }
          >
            Cleared the risk guardrails — approve to add to the paper watchlist.
          </Banner>
        )}

        {status === "completed" && watchlist.length > 0 && (
          <Banner tone="up" icon={<CheckCircle2 className="h-4 w-4" />} title="In the paper watchlist">
            <span className="font-mono">{watchlist.join("  ·  ")}</span>
          </Banner>
        )}

        {status === "rejected" && rejection && (
          <Banner tone="down" icon={<AlertTriangle className="h-4 w-4" />} title="No stocks cleared">
            {rejection}
          </Banner>
        )}

        {recs.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {recs.map((rec) => (
              <RecommendationCard key={rec.symbol} rec={rec} risk={risks[rec.symbol]} />
            ))}
          </div>
        ) : (
          <div className="flex h-40 items-center justify-center border border-dashed border-border">
            <span className="eyebrow">No recommendations in this run</span>
          </div>
        )}
      </div>

      <ApprovalModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        actionId={payload.action_id}
        items={passItems}
        onResolved={onResolved}
      />
    </div>
  );
}

function statusPill(status: string): string {
  if (status === "completed") return "pill-pass";
  if (status === "rejected" || status === "error") return "pill-reject";
  return "pill-flag";
}

function Banner({
  tone,
  icon,
  title,
  children,
  action,
}: {
  tone: "up" | "down" | "flag";
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const border = { up: "border-l-up", down: "border-l-down", flag: "border-l-flag" }[tone];
  const text = { up: "text-up", down: "text-down", flag: "text-flag" }[tone];
  return (
    <div className={`flex items-center justify-between gap-3 border border-border border-l-2 ${border} bg-card p-3`}>
      <div className="flex items-start gap-2.5">
        <span className={text}>{icon}</span>
        <div>
          <div className={`eyebrow ${text}`}>{title}</div>
          {children && <div className="mt-0.5 text-[0.8rem] text-muted-foreground">{children}</div>}
        </div>
      </div>
      {action}
    </div>
  );
}
