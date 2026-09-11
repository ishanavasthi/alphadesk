import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The Lab's one banner shape, in three tones (`lab/a-console.html`).
 *
 * The terminal had four of these inlined across `ResultsDashboard` and
 * `AnalysisView` with a `border-l-2` colour each; issue #18 folded them into one
 * object so the approval gate, the failure and the confirmation are the same
 * thing wearing different status tokens. The gate is deliberately the loudest
 * element on the results view — it is the only moment the desk asks for
 * something.
 */
export function LabBanner({
  tone,
  title,
  children,
  action,
}: {
  tone: "warn" | "good" | "bad";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2.5 rounded-lg border px-4 py-3",
        tone === "warn" &&
          "border-[var(--adp-warn-bd)] bg-[var(--adp-warn-bg)] text-[var(--adp-warn-ink)]",
        tone === "good" &&
          "border-[var(--adp-good-bd)] bg-[var(--adp-good-bg)] text-[var(--adp-good-ink)]",
        tone === "bad" &&
          "border-[var(--adp-bad-bd)] bg-[var(--adp-bad-bg)] text-[var(--adp-bad-ink)]",
      )}
    >
      <div className="min-w-[14rem] flex-1">
        <div className="text-[13.5px] font-semibold">{title}</div>
        {children ? <div className="mt-0.5 text-[12.5px] opacity-90">{children}</div> : null}
      </div>
      {action ? <div className="flex items-center gap-2">{action}</div> : null}
    </div>
  );
}
