"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Loader2, ShieldCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getRunStatus, type RunStatusPayload } from "@/lib/api";

/**
 * The run the desk should offer to re-attach to.
 *
 * Only the run **id** is stored — an opaque handle, never any of the run's
 * content — in `sessionStorage`, so it is scoped to this tab and dies with it.
 * That is the right scope: the backend keeps Lab runs in memory for the length
 * of a process, and the id is worthless to anyone else (every read is checked
 * against the caller's identity and answers 404 for a stranger's run).
 */
const KEY = "alphadesk.lab.lastRun";

export function rememberLabRun(runId: string): void {
  try {
    sessionStorage.setItem(KEY, runId);
  } catch {
    // Private mode / storage disabled — re-attach is a convenience, not a feature.
  }
}

export function forgetLabRun(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* see above */
  }
}

export function readLabRun(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

/**
 * The re-attach banner: "you have a run from this session — View →".
 *
 * Deliberately not a redirect. Leaving the Lab and coming back should not hijack
 * the desk; the query box stays usable for a new thesis and this sits above it.
 *
 * A run the backend can no longer find (it restarted — Lab runs are in memory by
 * design) is not an error to show a user who did not ask for it: the remembered
 * id is dropped and the desk renders as if nothing had been remembered.
 */
export function ResumeRunCard() {
  const [run, setRun] = useState<RunStatusPayload | null>(null);

  useEffect(() => {
    const id = readLabRun();
    if (!id) return;
    let cancelled = false;
    getRunStatus(id)
      .then((s) => {
        if (!cancelled) setRun(s);
      })
      .catch(() => {
        if (cancelled) return;
        forgetLabRun();
        setRun(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!run) return null;

  const running = run.status === "running";
  const awaiting = run.status === "awaiting_approval";

  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border border-border border-l-2 border-l-primary bg-card p-3">
      <div className="flex items-start gap-2.5">
        <span className="text-primary">
          {running ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <ShieldCheck className="h-4 w-4" />
          )}
        </span>
        <div className="min-w-0">
          <div className="eyebrow text-primary">
            {running
              ? "A run from this session is in progress"
              : awaiting
                ? "A run from this session is awaiting your approval"
                : "A run from this session has finished"}
          </div>
          <div className="mt-0.5 truncate text-[0.8rem] text-muted-foreground">
            <span className="font-mono">{run.run_id.slice(0, 8)}</span>
            {run.query ? ` · ${run.query}` : ""}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" asChild>
          <Link href={`/lab/a/${run.run_id}`}>
            View
            <ArrowRight />
          </Link>
        </Button>
        <Button
          variant="outline"
          size="sm"
          aria-label="Clear remembered run"
          onClick={() => {
            forgetLabRun();
            setRun(null);
          }}
        >
          <X />
          Clear
        </Button>
      </div>
    </div>
  );
}
