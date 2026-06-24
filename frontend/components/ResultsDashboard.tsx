"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, AlertTriangle, CheckCircle2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AgentStepCard, type StageStatus } from "@/components/AgentStepCard";
import { RecommendationCard } from "@/components/RecommendationCard";
import { ApprovalModal } from "@/components/ApprovalModal";
import {
  streamAnalyze,
  type AgentUpdate,
  type AnalystRecommendation,
  type ApproveResult,
  type CompleteEvent,
  type RiskAssessment,
} from "@/lib/api";

const STAGES = [
  { key: "scanner", code: "SCAN", name: "Scanner", countKey: "scan_results_count", noun: "candidates" },
  { key: "research", code: "RSRCH", name: "Research", countKey: "research_reports_count", noun: "researched" },
  { key: "analyst", code: "ANLYST", name: "Analyst", countKey: "analyst_recommendations_count", noun: "calls" },
  { key: "risk_manager", code: "RISK", name: "Risk Manager", countKey: "risk_assessments_count", noun: "assessed" },
  { key: "execution", code: "EXEC", name: "Execution", countKey: "approved_actions_count", noun: "approved" },
] as const;

type RunStatus = "running" | "awaiting_approval" | "completed" | "rejected" | "error";

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
    setStatus("running");
    setModalOpen(false);
    setStages((s) => ({ ...s, scanner: "active" }));

    streamAnalyze(
      query,
      {
        onStart: (e) => setRunId(e.run_id),
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
        onError: (msg) => {
          setError(msg);
          setStatus("error");
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

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      {/* Command echo header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
        <div className="min-w-0">
          <div className="font-mono text-sm">
            <span className="text-primary">query{">"}</span>{" "}
            <span className="text-foreground">{query}</span>
          </div>
          <div className="mt-1 flex items-center gap-3 eyebrow">
            <span>RUN {runId ? runId.slice(0, 8) : "········"}</span>
            <StatusTag status={status} />
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onReset}>
          <ArrowLeft />
          New query
        </Button>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
        {/* Pipeline rail — the signature element */}
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="eyebrow mb-2">Pipeline</div>
          <div className="space-y-1.5">
            {STAGES.map((s, i) => (
              <AgentStepCard
                key={s.key}
                index={i + 1}
                code={s.code}
                name={s.name}
                status={stages[s.key]}
                detail={details[s.key]}
              />
            ))}
          </div>
        </aside>

        {/* Results */}
        <section className="space-y-4">
          {error && (
            <Banner tone="down" icon={<AlertTriangle className="h-4 w-4" />} title="Run failed">
              {error}
            </Banner>
          )}

          {status === "awaiting_approval" && (
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
              The desk paused at the human-in-the-loop gate before staging anything.
            </Banner>
          )}

          {status === "completed" && watchlist.length > 0 && (
            <Banner tone="up" icon={<CheckCircle2 className="h-4 w-4" />} title="Added to paper watchlist">
              <span className="font-mono">{watchlist.join("  ·  ")}</span>
            </Banner>
          )}

          {status === "rejected" && rejectionReason && (
            <Banner tone="down" icon={<AlertTriangle className="h-4 w-4" />} title="No stocks cleared">
              {rejectionReason}
            </Banner>
          )}

          {recs.length > 0 ? (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {recs.map((rec) => (
                <RecommendationCard key={rec.symbol} rec={rec} risk={risks[rec.symbol]} />
              ))}
            </div>
          ) : (
            status === "running" && (
              <div className="flex h-40 items-center justify-center border border-dashed border-border text-center">
                <span className="eyebrow caret">Running the research desk</span>
              </div>
            )
          )}
        </section>
      </div>

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

function StatusTag({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, string> = {
    running: "pill-flag",
    awaiting_approval: "pill-flag",
    completed: "pill-pass",
    rejected: "pill-reject",
    error: "pill-reject",
  };
  return <span className={`pill ${map[status]}`}>{status.replace("_", " ")}</span>;
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
