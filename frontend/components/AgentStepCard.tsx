import { Check, Loader2, Clock, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

export type StageStatus = "pending" | "active" | "done" | "await" | "skipped";

interface AgentStepCardProps {
  index: number;
  code: string;
  name: string;
  status: StageStatus;
  detail?: string;
}

const META: Record<
  StageStatus,
  { label: string; dot: string; accent: string; text: string }
> = {
  pending: { label: "Queued", dot: "bg-muted-foreground/40", accent: "border-l-border", text: "text-muted-foreground" },
  active: { label: "Running", dot: "bg-flag animate-pulse-ring", accent: "border-l-flag", text: "text-flag" },
  done: { label: "Done", dot: "bg-up", accent: "border-l-up", text: "text-up" },
  await: { label: "Awaiting approval", dot: "bg-flag animate-pulse-ring", accent: "border-l-flag", text: "text-flag" },
  skipped: { label: "Skipped", dot: "bg-muted-foreground/40", accent: "border-l-border", text: "text-muted-foreground" },
};

function StatusIcon({ status }: { status: StageStatus }) {
  if (status === "done") return <Check className="h-3.5 w-3.5 text-up" />;
  if (status === "active") return <Loader2 className="h-3.5 w-3.5 animate-spin text-flag" />;
  if (status === "await") return <Clock className="h-3.5 w-3.5 text-flag" />;
  if (status === "skipped") return <Minus className="h-3.5 w-3.5 text-muted-foreground" />;
  return <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />;
}

export function AgentStepCard({ index, code, name, status, detail }: AgentStepCardProps) {
  const meta = META[status];
  const settled = status === "done" || status === "skipped";

  return (
    <div
      className={cn(
        "border-l-2 bg-card/60 px-3 py-2.5 transition-colors",
        meta.accent,
        status === "pending" && "opacity-55",
        settled && "animate-fade-in-up",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="font-mono text-[0.65rem] text-muted-foreground">
            {String(index).padStart(2, "0")}
          </span>
          <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
          <div className="leading-tight">
            <div className="font-mono text-xs font-semibold tracking-[0.08em] text-foreground">
              {code}
            </div>
            <div className="text-[0.7rem] text-muted-foreground">{name}</div>
          </div>
        </div>
        <StatusIcon status={status} />
      </div>
      <div className="mt-1.5 flex items-center justify-between pl-[1.65rem]">
        <span className={cn("eyebrow", meta.text)}>{meta.label}</span>
        {detail && status === "done" && (
          <span className="font-mono text-[0.65rem] text-muted-foreground">{detail}</span>
        )}
      </div>
    </div>
  );
}
