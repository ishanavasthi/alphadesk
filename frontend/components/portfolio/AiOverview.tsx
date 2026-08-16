"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  streamOverview,
  type OverviewComplete,
  type OverviewMetric,
  type OverviewParagraph,
  type OverviewSegment,
} from "@/lib/api";
import { Badge, Button, Card } from "@/components/portfolio/ui";

/**
 * The AI overview panel (card A1) — `docs/design/a2-overview.html`.
 *
 * The one rule this component is built around: **every number comes from the
 * computed-metrics payload, never from the model.** The narrative renders inline
 * "metric chips", and each chip's figure is the Python-computed `display` the
 * backend returned — the model only chose which metric to cite. The computed-
 * metrics rail on the right lists every number the narrative may reference, so a
 * reader can check any claim against its source.
 *
 * **It renders completely without the LLM.** When the model is unavailable the
 * stream still delivers every metric with `degraded: true`; the panel then shows
 * "AI overview unavailable" where the narrative would be, and the metrics rail is
 * unchanged. The dashboard never depends on the model.
 */

const AGENTS = [
  "allocation_critic",
  "concentration_risk",
  "sip_health",
  "performance_attribution",
  "synthesizer",
] as const;

type AgentState = "idle" | "running" | "done";
type Phase = "loading" | "ready" | "degraded" | "error" | "locked";

const DEGRADE_COPY: Record<string, string> = {
  llm_unavailable: "AI overview unavailable — the model could not be reached.",
  spend_cap: "AI overview paused — the daily generation budget is reached.",
  error: "AI overview unavailable — the narrative could not be generated.",
};

export function AiOverview() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [narrative, setNarrative] = useState<OverviewParagraph[]>([]);
  const [metrics, setMetrics] = useState<OverviewMetric[]>([]);
  const [reason, setReason] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [agentStates, setAgentStates] = useState<Record<string, AgentState>>({});
  const [runKey, setRunKey] = useState(0);
  const aborter = useRef<AbortController | null>(null);

  const applyComplete = useCallback((data: OverviewComplete) => {
    setMetrics(data.metrics);
    setNarrative(data.narrative);
    setReason(data.reason);
    setPhase(data.degraded ? "degraded" : "ready");
    setAgentStates((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(next)) next[key] = "done";
      return next;
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    aborter.current?.abort();
    aborter.current = controller;

    setPhase("loading");
    setNarrative([]);
    setReason(null);
    setAgentStates(Object.fromEntries(AGENTS.map((a) => [a, "running" as AgentState])));

    void streamOverview(
      {
        onStart: () => setPhase("loading"),
        onUpdate: ({ node }) =>
          setAgentStates((prev) => ({ ...prev, [node]: "done" })),
        onComplete: applyComplete,
        onError: (message, status) => {
          if (status === 0) {
            setPhase("locked");
          } else {
            setErrorMessage(message);
            setPhase("error");
          }
        },
      },
      controller.signal,
    );

    return () => controller.abort();
  }, [runKey, applyComplete]);

  const regenerate = useCallback(() => setRunKey((k) => k + 1), []);

  const shown = metrics.filter((m) => m.available);

  return (
    <Card className="mt-4 grid grid-cols-1 gap-0 overflow-hidden p-0 lg:grid-cols-[2fr_1fr]">
      {/* Left — narrative + agents */}
      <div className="border-b border-border p-5 lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-semibold leading-tight">AI overview</h2>
          <Badge variant="lab">gpt · portfolio agents</Badge>
          <span className="flex-1" />
          <Button
            variant="outline"
            size="sm"
            onClick={regenerate}
            disabled={phase === "loading"}
            aria-label="Regenerate the AI overview"
          >
            ✦ Regenerate
          </Button>
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1.5" aria-hidden={phase === "locked"}>
          {AGENTS.map((agent) => (
            <AgentChip key={agent} name={agent} state={agentStates[agent] ?? "idle"} />
          ))}
        </div>

        <div className="mt-3">
          {phase === "loading" ? (
            <p className="text-[13px] text-muted-foreground">Reading your metrics and writing the overview…</p>
          ) : phase === "error" ? (
            <DegradedBox message={errorMessage || "The overview could not be loaded."} />
          ) : phase === "locked" ? (
            <p className="text-[13px] text-muted-foreground">Sign in to load the AI overview.</p>
          ) : phase === "degraded" || narrative.length === 0 ? (
            <DegradedBox message={DEGRADE_COPY[reason ?? "error"] ?? DEGRADE_COPY.error} degraded />
          ) : (
            <Narrative paragraphs={narrative} />
          )}
        </div>

        <p className="mt-3.5 text-[11.5px] leading-relaxed text-[var(--adp-faint)]">
          Every figure above is computed in Python and shown beside its claim — the agents narrate
          verified metrics and never invent numbers. Descriptive analytics only; not investment advice.
        </p>
      </div>

      {/* Right — computed metrics rail + degraded note */}
      <div className="bg-secondary/40 p-5">
        <h3 className="mb-2.5 text-sm font-semibold">Computed metrics</h3>
        {shown.length === 0 ? (
          <p className="text-xs text-muted-foreground">Metrics load with the panel.</p>
        ) : (
          <dl className="text-[13px]">
            {shown.map((m) => (
              <div
                key={m.key}
                className="flex items-baseline justify-between gap-2 border-b border-border py-[9px] last:border-b-0"
              >
                <dt className="text-[12.5px] text-muted-foreground">{m.label}</dt>
                <dd className="font-semibold tabular-nums">
                  {m.display}
                  {m.detail && m.unit !== "text" ? (
                    <small className="ml-1 font-normal text-[var(--adp-faint)]">{m.detail}</small>
                  ) : null}
                </dd>
              </div>
            ))}
          </dl>
        )}
        <div className="mt-4 rounded-md border border-dashed border-border bg-card p-2.5 text-xs text-muted-foreground">
          <b className="font-semibold text-foreground">If the model is unavailable</b>, this panel
          says &ldquo;AI overview unavailable&rdquo; — every number on this page still renders. The
          dashboard never depends on the LLM.
        </div>
      </div>
    </Card>
  );
}

function Narrative({ paragraphs }: { paragraphs: OverviewParagraph[] }) {
  return (
    <div className="space-y-2.5 text-[13.5px] leading-[1.75] text-[#27272a]">
      {paragraphs.map((para, i) => (
        <p key={i}>
          {para.segments.map((seg, j) => (
            <Segment key={j} seg={seg} />
          ))}
        </p>
      ))}
    </div>
  );
}

function Segment({ seg }: { seg: OverviewSegment }) {
  if ("text" in seg) return <>{seg.text}</>;
  // A metric chip: the figure is the Python-computed display, never model text.
  return (
    <span
      className="mx-px inline-block rounded-full border border-[var(--adp-accent-ring)] bg-[var(--adp-accent-soft)] px-1.5 py-px text-[12px] font-semibold text-[#1d4ed8] tabular-nums"
      title={seg.label}
    >
      {seg.display}
    </span>
  );
}

function AgentChip({ name, state }: { name: string; state: AgentState }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2 py-[3px] text-[11.5px] text-muted-foreground">
      <span
        aria-hidden
        className={
          state === "done"
            ? "h-[6px] w-[6px] rounded-full bg-[var(--adp-good)]"
            : state === "running"
              ? "h-[6px] w-[6px] animate-pulse rounded-full bg-[var(--adp-accent)]"
              : "h-[6px] w-[6px] rounded-full bg-[var(--adp-faint)]"
        }
      />
      {name}
    </span>
  );
}

function DegradedBox({ message, degraded }: { message: string; degraded?: boolean }) {
  return (
    <div className="rounded-md border border-dashed border-border bg-card p-3 text-[13px] text-muted-foreground">
      <b className="font-semibold text-foreground">
        {degraded ? "AI overview unavailable" : "Couldn’t load the overview"}
      </b>
      <div className="mt-0.5">{message}</div>
      <div className="mt-1 text-xs text-[var(--adp-faint)]">
        Every computed number still renders in the rail and across this page.
      </div>
    </div>
  );
}
