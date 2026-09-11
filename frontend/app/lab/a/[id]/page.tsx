"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { AnalysisView } from "@/components/lab/AnalysisView";
import { PipelineStrip, type Stage } from "@/components/lab/PipelineStrip";
import { forgetLabRun, readLabRun } from "@/components/lab/ResumeRunCard";
import { RunHeader } from "@/components/lab/RunHeader";
import { Button, EmptyCallout } from "@/components/ui/adp";
import { getAnalysis, getRunStatus, type AnalysisPayload, type RunStatusPayload } from "@/lib/api";

/** How often to re-ask while the run is still working. */
const POLL_MS = 3000;

export default function AnalysisPage() {
  const params = useParams();
  const id = String(params.id);
  // undefined = loading, null = not found / error
  const [data, setData] = useState<AnalysisPayload | null | undefined>(undefined);
  // Set only while the run exists but has not produced an analysis yet.
  const [pending, setPending] = useState<RunStatusPayload | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    // `/analysis/{id}` is written when the run completes, so a run re-attached
    // mid-flight 404s there and is alive on `/status/{id}`. Ask both, in that
    // order, and keep asking until the finished analysis exists — the live step
    // timeline belongs to the SSE stream in the tab that started the run and
    // cannot be rebuilt here, but the result can.
    async function load() {
      try {
        const d = await getAnalysis(id);
        if (!cancelled) {
          setPending(null);
          setData(d);
        }
        return;
      } catch {
        // Not stored (yet) — maybe still running.
      }
      try {
        const s = await getRunStatus(id);
        if (cancelled) return;
        if (s.status === "running") {
          setPending(s);
          timer = setTimeout(load, POLL_MS);
          return;
        }
      } catch {
        // No such run for this caller — fall through to the empty state.
      }
      if (cancelled) return;
      // The backend restarted (Lab runs live in memory, card F4). Drop the
      // remembered handle so the desk stops offering a run that is gone.
      if (readLabRun() === id) forgetLabRun();
      setPending(null);
      setData(null);
    }

    load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  if (pending) return <RunningView run={pending} />;

  if (data === undefined) {
    return (
      <div className="mt-8">
        <EmptyCallout icon="◌">Loading this analysis…</EmptyCallout>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mt-8 flex max-w-xl flex-col items-start gap-4">
        <EmptyCallout icon="⤫">
          <b className="font-semibold text-foreground">This analysis isn’t available.</b> It may
          still be running, or the backend restarted — Lab runs are held in memory, so a restart
          clears them. Your paper watchlist is unaffected.
        </EmptyCallout>
        <Button variant="outline" asChild>
          <Link href="/lab">
            <ArrowLeft className="h-3.5 w-3.5" />
            Start a new query
          </Link>
        </Button>
      </div>
    );
  }

  return <AnalysisView payload={data} />;
}

/**
 * The in-flight view: everything known about a run that has not finished.
 *
 * The strip is drawn honestly — this page polls a status endpoint and cannot
 * know which agent is mid-sentence, so it says the run is working rather than
 * animating a timeline it does not have.
 */
function RunningView({ run }: { run: RunStatusPayload }) {
  const stages: Stage[] = [
    { key: "scanner", name: "Scanner", status: "active" },
    { key: "research", name: "Research", status: "pending" },
    { key: "analyst", name: "Analyst", status: "pending" },
    { key: "risk_manager", name: "Risk Manager", status: "pending" },
    { key: "execution", name: "Execution", status: "pending" },
  ];

  return (
    <div className="pb-2">
      <RunHeader
        query={run.query}
        runId={run.run_id}
        status="running"
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
        <PipelineStrip stages={stages} />
        <EmptyCallout icon="◌">
          <b className="font-semibold text-foreground">The desk is still working.</b> The
          step-by-step timeline streams to the view that started the run; this page re-checks every
          few seconds and renders the result as soon as it lands.
        </EmptyCallout>
      </div>
    </div>
  );
}
