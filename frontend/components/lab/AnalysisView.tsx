"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { ApprovalModal } from "@/components/lab/ApprovalModal";
import { CandidateSections } from "@/components/lab/CandidateSections";
import { LabBanner } from "@/components/lab/LabBanner";
import { RunHeader, type RunStatus } from "@/components/lab/RunHeader";
import { Button } from "@/components/ui/adp";
import type { AnalysisPayload, ApproveResult, RiskAssessment } from "@/lib/api";

/**
 * A stored run, reopened at `/lab/a/<id>`.
 *
 * The same view as the live one minus the pipeline strip: the step timeline
 * belongs to the SSE stream in the tab that started the run and cannot be
 * rebuilt from a stored analysis, so this does not draw a fake one.
 */
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
    <div className="pb-2">
      <RunHeader
        query={payload.query}
        runId={payload.run_id}
        status={runStatus(status, awaiting)}
        createdAt={payload.created_at ? new Date(payload.created_at).toLocaleString() : undefined}
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link href="/lab">
              <ArrowLeft className="h-3.5 w-3.5" />
              New query
            </Link>
          </Button>
        }
      />

      <div className="mt-5 flex flex-col gap-4">
        {awaiting ? (
          <LabBanner
            tone="warn"
            title={`${passItems.length} candidate${passItems.length === 1 ? "" : "s"} cleared the guardrails`}
            action={
              <Button variant="primary" size="sm" onClick={() => setModalOpen(true)}>
                Review &amp; approve
              </Button>
            }
          >
            Nothing is staged until you approve. Approving adds them to the paper watchlist — no
            order is placed.
          </LabBanner>
        ) : null}

        {status === "completed" && watchlist.length > 0 ? (
          <LabBanner tone="good" title={`${watchlist.length} in your paper watchlist`}>
            {watchlist.join(" · ")} — the watchlist persists to your account. The run itself does
            not.
          </LabBanner>
        ) : null}

        {status === "rejected" && rejection ? (
          <LabBanner tone="bad" title="Nothing cleared the guardrails">
            {rejection}
          </LabBanner>
        ) : null}
      </div>

      <CandidateSections recs={recs} risks={risks} />

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

function runStatus(status: string, awaiting: boolean): RunStatus {
  if (awaiting) return "awaiting_approval";
  if (status === "completed") return "completed";
  if (status === "rejected") return "rejected";
  if (status === "error") return "error";
  return "running";
}
