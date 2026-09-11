"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, KeyRound, Loader2 } from "lucide-react";

import { useIndMoney } from "@/components/AuthProvider";
import { ApprovalModal } from "@/components/lab/ApprovalModal";
import { CandidateSections } from "@/components/lab/CandidateSections";
import { LabBanner } from "@/components/lab/LabBanner";
import { PipelineStrip, type Stage, type StageStatus } from "@/components/lab/PipelineStrip";
import { rememberLabRun } from "@/components/lab/ResumeRunCard";
import { RunHeader, type RunStatus } from "@/components/lab/RunHeader";
import { Button } from "@/components/ui/adp";
import {
  streamAnalyze,
  type AgentUpdate,
  type AnalystRecommendation,
  type ApproveResult,
  type CompleteEvent,
  type RiskAssessment,
} from "@/lib/api";

const STAGES = [
  { key: "scanner", name: "Scanner", countKey: "scan_results_count", noun: "candidates" },
  { key: "research", name: "Research", countKey: "research_reports_count", noun: "researched" },
  { key: "analyst", name: "Analyst", countKey: "analyst_recommendations_count", noun: "calls" },
  { key: "risk_manager", name: "Risk Manager", countKey: "risk_assessments_count", noun: "assessed" },
  { key: "execution", name: "Execution", countKey: "approved_actions_count", noun: "approved" },
] as const;

export function ResultsDashboard({ query, onReset }: { query: string; onReset: () => void }) {
  const [stages, setStages] = useState<Record<string, StageStatus>>(() =>
    Object.fromEntries(STAGES.map((s) => [s.key, "pending" as StageStatus])),
  );
  const [details, setDetails] = useState<Record<string, string>>({});
  const [recs, setRecs] = useState<AnalystRecommendation[]>([]);
  const [risks, setRisks] = useState<Record<string, RiskAssessment>>({});
  const [runId, setRunId] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus>("running");
  const [error, setError] = useState<string | null>(null);
  // 409 from /analyze means the backend lost its IND Money session mid-session.
  const [needsAuth, setNeedsAuth] = useState(false);
  const { busy: authBusy, connect } = useIndMoney();
  const [rejectionReason, setRejectionReason] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    // Reset for a fresh run (also covers a re-query on the same instance).
    setStages(Object.fromEntries(STAGES.map((s) => [s.key, "pending" as StageStatus])));
    setDetails({});
    setRecs([]);
    setRisks({});
    setActionId(null);
    setRejectionReason(null);
    setWatchlist([]);
    setError(null);
    setNeedsAuth(false);
    setStatus("running");
    setModalOpen(false);
    setStages((s) => ({ ...s, scanner: "active" }));

    streamAnalyze(
      query,
      {
        onStart: (e) => {
          setRunId(e.run_id);
          // Reflect the run in the URL so a refresh reopens it at /lab/a/<run_id>.
          if (typeof window !== "undefined") {
            window.history.replaceState(null, "", `/lab/a/${e.run_id}`);
            // …and remember it for this tab, so leaving the Lab and coming back
            // offers the run instead of forgetting it ever happened. A new run
            // overwrites the id — only one run is ever remembered.
            rememberLabRun(e.run_id);
          }
        },
        onUpdate: (e: AgentUpdate) => {
          const stage = STAGES.find((s) => s.key === e.node);
          if (!stage) return;
          const count = e[stage.countKey];
          setDetails((d) => ({
            ...d,
            [stage.key]: typeof count === "number" ? `${count} ${stage.noun}` : "",
          }));
          setStages((prev) => {
            const next = { ...prev, [stage.key]: "done" as StageStatus };
            const idx = STAGES.findIndex((s) => s.key === stage.key);
            const upcoming = STAGES[idx + 1];
            if (upcoming && next[upcoming.key] === "pending") next[upcoming.key] = "active";
            return next;
          });
        },
        onComplete: (e: CompleteEvent) => {
          setRecs(e.analyst_recommendations || []);
          setRisks(
            Object.fromEntries((e.risk_assessments || []).map((r) => [r.symbol, r])),
          );
          if (e.awaiting_approval && e.action_id) {
            setActionId(e.action_id);
            setStatus("awaiting_approval");
            setStages((s) => ({ ...s, execution: "await" }));
            setModalOpen(true);
          } else if (e.rejection_reason) {
            setRejectionReason(e.rejection_reason);
            setStatus("rejected");
            setStages((s) => ({ ...s, execution: "skipped" }));
          } else {
            setStatus("completed");
            setStages((s) => ({ ...s, execution: "skipped" }));
          }
        },
        onError: (msg, httpStatus) => {
          setError(msg);
          setNeedsAuth(httpStatus === 409);
          setStatus("error");
          // Don't leave the strip pulsing on a stage that will never run.
          setStages((prev) =>
            Object.fromEntries(
              Object.entries(prev).map(([k, v]) => [
                k,
                v === "done" ? v : ("skipped" as StageStatus),
              ]),
            ),
          );
        },
      },
      controller.signal,
    );

    return () => controller.abort();
  }, [query]);

  function onResolved(approved: boolean, result: ApproveResult) {
    if (approved) {
      setStatus("completed");
      setStages((s) => ({ ...s, execution: "done" }));
      setWatchlist(result.state?.paper_watchlist ?? []);
      setDetails((d) => ({
        ...d,
        execution: `${result.state?.paper_watchlist?.length ?? 0} approved`,
      }));
    } else {
      setStatus("rejected");
      setStages((s) => ({ ...s, execution: "skipped" }));
      setRejectionReason("Rejected by analyst.");
    }
  }

  // Approvable = anything that cleared the guardrails (PASS or FLAG).
  const passItems = recs
    .map((rec) => ({ rec, risk: risks[rec.symbol] }))
    .filter((x) => x.risk?.approved === true);

  const strip: Stage[] = STAGES.map((s) => ({
    key: s.key,
    name: s.name,
    status: stages[s.key],
    detail: stages[s.key] === "done" ? details[s.key] || undefined : undefined,
  }));

  return (
    <div className="pb-2">
      <RunHeader
        query={query}
        runId={runId}
        status={status}
        actions={
          <Button variant="outline" size="sm" onClick={onReset}>
            <ArrowLeft className="h-3.5 w-3.5" />
            New query
          </Button>
        }
      />

      <div className="mt-5 flex flex-col gap-4">
        <PipelineStrip stages={strip} />

        {error ? (
          <LabBanner
            tone="bad"
            title={needsAuth ? "IND Money isn’t connected" : "The run failed"}
            action={
              needsAuth ? (
                <Button variant="accent" size="sm" onClick={connect} disabled={authBusy}>
                  {authBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <KeyRound className="h-3.5 w-3.5" />
                  )}
                  Connect
                </Button>
              ) : undefined
            }
          >
            {error}
          </LabBanner>
        ) : null}

        {status === "awaiting_approval" ? (
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
          <LabBanner tone="good" title={`${watchlist.length} added to your paper watchlist`}>
            {watchlist.join(" · ")} — the watchlist persists to your account. The run itself does
            not.
          </LabBanner>
        ) : null}

        {status === "rejected" && rejectionReason ? (
          <LabBanner tone="bad" title="Nothing cleared the guardrails">
            {rejectionReason}
          </LabBanner>
        ) : null}
      </div>

      {recs.length > 0 ? (
        <CandidateSections recs={recs} risks={risks} />
      ) : status === "running" ? (
        <RunningSkeleton />
      ) : null}

      <ApprovalModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        actionId={actionId}
        items={passItems}
        onResolved={onResolved}
      />
    </div>
  );
}

/**
 * What the results area shows while the desk is still working.
 *
 * Three card outlines rather than a spinner: the reader is about to get cards,
 * and saying so costs nothing. Explicitly labelled so it never reads as content.
 */
function RunningSkeleton() {
  return (
    <div className="mt-8">
      <div className="mb-3.5 text-[15px] font-semibold tracking-[-0.01em]">
        Running the research desk…
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3" aria-hidden>
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-lg border border-border bg-card p-5">
            <div className="h-2.5 w-24 animate-pulse rounded bg-secondary" />
            <div className="mt-3 h-2 w-full animate-pulse rounded bg-secondary" />
            <div className="mt-2 h-2 w-4/5 animate-pulse rounded bg-secondary" />
            <div className="mt-2 h-2 w-2/3 animate-pulse rounded bg-secondary" />
          </div>
        ))}
      </div>
    </div>
  );
}
