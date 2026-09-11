import type { ReactNode } from "react";

import { Badge } from "@/components/ui/adp";

export type RunStatus = "running" | "awaiting_approval" | "completed" | "rejected" | "error";

const STATUS: Record<RunStatus, { variant: "good" | "warn" | "bad"; label: string }> = {
  running: { variant: "warn", label: "Running" },
  awaiting_approval: { variant: "warn", label: "Awaiting approval" },
  completed: { variant: "good", label: "Completed" },
  rejected: { variant: "bad", label: "Nothing cleared" },
  error: { variant: "bad", label: "Failed" },
};

/**
 * The command echo: what was asked, which run answered it, and where it got to.
 *
 * The terminal rendered this as `query>` in mono with an amber caret. Issue #18
 * made the query itself the page's title — it is the one thing on the view the
 * reader wrote — and demoted the machinery to the caption under it. The run id
 * stays monospaced because it is an identifier people copy into a URL, which is
 * the one job mono still has on this surface.
 */
export function RunHeader({
  query,
  runId,
  status,
  elapsed,
  createdAt,
  actions,
}: {
  /** The thesis the reader typed. The status endpoint may not carry it. */
  query?: string | null;
  runId: string | null;
  status: RunStatus;
  /** Seconds the run has taken, when the view knows. */
  elapsed?: string;
  createdAt?: string;
  actions?: ReactNode;
}) {
  const s = STATUS[status];
  return (
    <header className="mt-6 flex flex-wrap items-start gap-x-4 gap-y-3">
      <div className="min-w-[16rem] flex-1">
        <div className="text-xs text-muted-foreground">Query</div>
        {/* Unknown is said, not faked: a stored run whose query the status
            endpoint did not carry gets a caption, never an empty heading. */}
        <h1 className="mt-0.5 text-[19px] font-semibold leading-snug tracking-[-0.02em]">
          {query || <span className="text-[var(--adp-faint)]">Query not recorded</span>}
        </h1>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--adp-faint)]">
          <span className="adp-num font-mono text-muted-foreground">
            run {runId ? runId.slice(0, 8) : "········"}
          </span>
          {createdAt ? (
            <>
              <span aria-hidden>·</span>
              <span>{createdAt}</span>
            </>
          ) : null}
          {elapsed ? (
            <>
              <span aria-hidden>·</span>
              <span className="adp-num">{elapsed}</span>
            </>
          ) : null}
          <span aria-hidden>·</span>
          <Badge variant={s.variant}>{s.label}</Badge>
        </div>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
