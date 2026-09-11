import { cn } from "@/lib/utils";

export type StageStatus = "pending" | "active" | "done" | "await" | "skipped";

export interface Stage {
  key: string;
  name: string;
  status: StageStatus;
  /** What the agent produced — "18 candidates". Only shown once it is settled. */
  detail?: string;
}

/**
 * The five agents as one strip (`docs/design/lab/a-console.html`).
 *
 * The order is the real dependency chain — each agent consumes the one before
 * it — so left-to-right and the rule that fills under it are information, not
 * decoration. That is also why it is a single bordered object rather than five
 * cards: it is one pipeline, and five cards would say five things.
 *
 * This replaced `AgentStepCard`, the terminal's vertical rail of amber-striped
 * rows (issue #18). Colour here is status only: the accent rule marks work that
 * is finished, `--adp-warn-mark` the stage that has stopped and is waiting on a
 * human, and an unstarted stage gets no rule at all.
 */
export function PipelineStrip({ stages }: { stages: Stage[] }) {
  return (
    <ol
      aria-label="Pipeline"
      className="grid grid-cols-2 overflow-hidden rounded-lg border border-border bg-card shadow-[0_1px_2px_var(--adp-shadow)] sm:grid-cols-3 lg:grid-cols-5"
    >
      {stages.map((s, i) => {
        const waiting = s.status === "await" || s.status === "active";
        const settled = s.status === "done";
        const idle = s.status === "pending" || s.status === "skipped";
        return (
          <li
            key={s.key}
            // The cell owns its own separators so the strip reads as one object
            // at every breakpoint: a left rule except at the start of a row, a
            // top rule except on the first row.
            className={cn(
              "relative border-border px-3.5 py-3",
              i > 0 && "border-l",
              "[&:nth-child(odd)]:border-l-0 sm:[&:nth-child(odd)]:border-l",
              "sm:[&:nth-child(3n+1)]:border-l-0 lg:[&:nth-child(3n+1)]:border-l",
              "lg:[&:nth-child(5n+1)]:border-l-0",
              i > 1 && "border-t sm:border-t-0",
              i > 2 && "sm:border-t lg:border-t-0",
            )}
          >
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className={cn(
                  "h-2 w-2 shrink-0 rounded-full",
                  settled && "bg-[var(--adp-good)]",
                  waiting && "animate-pulse bg-[var(--adp-warn-mark)]",
                  idle && "bg-[var(--adp-faint)]",
                )}
              />
              <span
                className={cn(
                  "text-[12.5px] font-medium",
                  idle && "text-[var(--adp-faint)]",
                )}
              >
                {s.name}
              </span>
            </div>
            <div
              className={cn(
                "adp-num mt-1 text-xs",
                idle ? "text-[var(--adp-faint)]" : "text-muted-foreground",
              )}
            >
              {s.detail ?? STATUS_TEXT[s.status]}
            </div>
            <span
              aria-hidden
              className={cn(
                "absolute inset-x-0 bottom-0 h-0.5",
                settled && "bg-[var(--adp-accent)]",
                waiting && "bg-[var(--adp-warn-mark)]",
              )}
            />
          </li>
        );
      })}
    </ol>
  );
}

/** What a stage says before it has produced anything countable. */
const STATUS_TEXT: Record<StageStatus, string> = {
  pending: "Queued",
  active: "Running…",
  done: "Done",
  await: "Paused — awaiting you",
  skipped: "Not reached",
};
