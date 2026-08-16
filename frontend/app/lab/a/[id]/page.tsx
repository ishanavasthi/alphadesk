"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { getAnalysis, getRunStatus, type AnalysisPayload, type RunStatusPayload } from "@/lib/api";
import { AnalysisView } from "@/components/AnalysisView";
import { forgetLabRun, readLabRun } from "@/components/ResumeRunCard";

const PIPELINE = ["SCAN", "RESEARCH", "ANALYSE", "RISK", "EXECUTE"];

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
      <div className="flex h-[60vh] items-center justify-center">
        <span className="eyebrow caret">Loading analysis</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto flex h-[60vh] max-w-md flex-col items-center justify-center gap-3 px-4 text-center">
        <p className="text-sm text-muted-foreground">
          This analysis isn&apos;t available. It may still be running, or the backend
          restarted (runs are kept in memory).
        </p>
        <Link href="/lab" className="font-mono text-xs uppercase tracking-[0.1em] text-primary hover:underline">
          ← Start a new query
        </Link>
      </div>
    );
  }

  return <AnalysisView payload={data} />;
}

/** The in-flight view: everything known about a run that has not finished. */
function RunningView({ run }: { run: RunStatusPayload }) {
  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
        <div className="min-w-0">
          <div className="font-mono text-sm">
            <span className="text-primary">query{">"}</span>{" "}
            <span className="text-foreground">{run.query}</span>
          </div>
          <div className="mt-1 flex items-center gap-3 eyebrow">
            <span>RUN {run.run_id.slice(0, 8)}</span>
            <span className="pill pill-flag">running</span>
          </div>
        </div>
        <Link
          href="/lab"
          className="font-mono text-xs uppercase tracking-[0.1em] text-primary hover:underline"
        >
          ← New query
        </Link>
      </div>

      <div className="mt-5 border border-border border-l-2 border-l-flag bg-card p-3">
        <div className="flex items-start gap-2.5">
          <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-flag" />
          <div>
            <div className="eyebrow text-flag">Run in progress</div>
            <div className="mt-0.5 text-[0.8rem] text-muted-foreground">
              The desk is still working. The step-by-step timeline streams to the
              view that started the run; this page checks every few seconds and
              renders the result as soon as it lands.
            </div>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-2 border-t border-border pt-3">
          <span className="eyebrow mr-1">Pipeline</span>
          {PIPELINE.map((p, i) => (
            <span key={p} className="flex items-center gap-2">
              <span className="font-mono text-[0.7rem] tracking-[0.1em] text-muted-foreground">
                {p}
              </span>
              {i < PIPELINE.length - 1 && <span className="text-border">▸</span>}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
