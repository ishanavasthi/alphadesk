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
import { MASK, useAmountsHidden } from "@/components/portfolio/privacy";

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
 *
 * ## Static mode (`initial`) — the `/demo` path
 *
 * Passing `initial` renders the panel from a **committed** overview and makes
 * **no stream**: card U1's public `/demo` route serves card A1's frozen
 * narrative artifact this way, so an anonymous visitor never triggers an LLM
 * call. The streaming effect is skipped entirely (not merely ignored), and the
 * Regenerate button — which would need a live stream — is hidden.
 *
 * ## Cached mode (`cached` + `onComplete`) — the dashboard's back button
 *
 * `cached` is the same "render a finished overview, make no stream" behaviour,
 * but it **keeps** Regenerate: the run is over, not frozen. The dashboard's
 * route layout holds the last completed overview and hands it back here, so
 * walking to Holdings and returning re-reads what is already written instead of
 * paying five agents to say it again. `onComplete` is how the run gets there.
 *
 * That cache only survives the session. The backend keeps the other half: the
 * narrative is written at most once per IST day, so a reload or a re-login gets
 * today's saved copy back over the same stream. **Regenerate is the only thing
 * that spends** — it sends `force`, which re-runs the agents and overwrites the
 * day's saved narrative.
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

/** All agents marked done — the state a committed (already-run) overview is in. */
function allDone(): Record<string, AgentState> {
  return Object.fromEntries(AGENTS.map((a) => [a, "done" as AgentState]));
}

export function AiOverview({
  initial,
  cached,
  onComplete,
}: {
  initial?: OverviewComplete;
  /** A completed run to re-render instead of streaming a fresh one. */
  cached?: OverviewComplete | null;
  /** Called with every live run that completes, so a caller can keep it. */
  onComplete?: (data: OverviewComplete) => void;
} = {}) {
  // Both modes start from a finished overview; only `initial` also gives up the
  // Regenerate button, because /demo has no stream to regenerate against.
  const seed = initial ?? cached ?? null;
  const [phase, setPhase] = useState<Phase>(
    seed ? (seed.degraded ? "degraded" : "ready") : "loading",
  );
  const [narrative, setNarrative] = useState<OverviewParagraph[]>(seed?.narrative ?? []);
  const [metrics, setMetrics] = useState<OverviewMetric[]>(seed?.metrics ?? []);
  const [reason, setReason] = useState<string | null>(seed?.reason ?? null);
  const [errorMessage, setErrorMessage] = useState("");
  const [agentStates, setAgentStates] = useState<Record<string, AgentState>>(
    seed ? allDone() : {},
  );
  const [runKey, setRunKey] = useState(0);
  const aborter = useRef<AbortController | null>(null);
  /**
   * Whether the cached run still stands in for a stream.
   *
   * Consumed once, on mount: pressing Regenerate must reach the model, and a
   * cache that kept swallowing runs would make the button a lie.
   */
  const cachedIsFresh = useRef(Boolean(cached));
  // Read through a ref so a caller passing an inline handler cannot restart the
  // stream by re-rendering.
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

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
    onCompleteRef.current?.(data);
  }, []);

  useEffect(() => {
    // Static mode: the overview is already in hand (card U1's /demo serves A1's
    // committed artifact). No stream, so a public visitor never hits the LLM.
    if (initial) return;
    // Cached mode: this run already happened on a previous visit to the page.
    if (cachedIsFresh.current) {
      cachedIsFresh.current = false;
      return;
    }

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
      // Mount is `runKey === 0` and asks for whatever the backend already wrote
      // today; every later run is a Regenerate press, the one thing allowed to
      // re-run the agents and overwrite the day's saved narrative.
      { force: runKey > 0 },
    );

    return () => controller.abort();
  }, [runKey, applyComplete, initial]);

  const regenerate = useCallback(() => setRunKey((k) => k + 1), []);

  const hideAmounts = useAmountsHidden();
  const metricUnits = new Map(metrics.map((m) => [m.key, m.unit]));
  const shown = metrics.filter((m) => m.available);

  return (
    <Card className="mt-4 grid grid-cols-1 gap-0 overflow-hidden p-0 lg:min-h-[320px] lg:grid-cols-[2fr_1fr]">
      {/* Left — narrative + agents */}
      <div className="min-w-0 border-b border-border p-5 lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-semibold leading-tight">AI overview</h2>
          <Badge variant="lab">gpt · portfolio agents</Badge>
          <span className="flex-1" />
          {initial ? null : (
            <Button
              variant="outline"
              size="sm"
              onClick={regenerate}
              disabled={phase === "loading"}
              aria-label="Regenerate the AI overview"
            >
              ✦ Regenerate
            </Button>
          )}
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
            <Narrative paragraphs={narrative} units={metricUnits} hide={hideAmounts} />
          )}
        </div>

        <p className="mt-3.5 text-[11.5px] leading-relaxed text-[var(--adp-faint)]">
          Every figure above is computed in Python and shown beside its claim — the agents narrate
          verified metrics and never invent numbers. Descriptive analytics only; not investment advice.
        </p>
      </div>

      {/* Right — computed metrics rail + degraded note.
          On `lg` the rail is taken out of flow (absolute inside this relative
          cell) so its ~18 rows contribute no height: the narrative column drives
          the card and the rail scrolls internally. Stacked below `lg` it flows
          normally, uncapped. */}
      <div className="relative min-w-0 bg-secondary/40">
        <div className="p-5 lg:absolute lg:inset-0 lg:overflow-y-auto">
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
                  <dt className="min-w-0 break-words text-[12.5px] text-muted-foreground">
                    {m.label}
                  </dt>
                  <dd className="min-w-0 break-words text-right font-semibold tabular-nums">
                    {maskFigure(m.display, m.unit, hideAmounts)}
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
      </div>
    </Card>
  );
}

/**
 * Mask a backend-rendered figure.
 *
 * This panel is the one place on the surface that does **not** go through
 * `format.ts`: every figure it shows is `display`, a string already rendered by
 * Python and shipped over the wire. A mask applied only at the formatter layer
 * would leave real rupee amounts sitting in the most quotable part of the page,
 * so the same rule is enforced a second time, here, on purpose.
 *
 * `unit === undefined` means the chip cites a metric the rail did not send. That
 * should not happen — chips and metrics arrive in the same payload — but the
 * failure is closed rather than open: an unclassifiable figure is hidden, minus
 * the rupee sign it may not deserve. A privacy control that leaks whatever it
 * fails to recognise is not one.
 */
function maskFigure(display: string, unit: string | undefined, hide: boolean): string {
  if (!hide) return display;
  if (unit === "inr") return `₹${MASK}`;
  if (unit === undefined) return MASK;
  return display;
}

function Narrative({
  paragraphs,
  units,
  hide,
}: {
  paragraphs: OverviewParagraph[];
  units: Map<string, string>;
  hide: boolean;
}) {
  return (
    <div className="space-y-2.5 text-[13.5px] leading-[1.75] text-[var(--adp-prose)]">
      {paragraphs.map((para, i) => (
        <p key={i}>
          {para.segments.map((seg, j) => (
            <Segment key={j} seg={seg} units={units} hide={hide} />
          ))}
        </p>
      ))}
    </div>
  );
}

function Segment({
  seg,
  units,
  hide,
}: {
  seg: OverviewSegment;
  units: Map<string, string>;
  hide: boolean;
}) {
  if ("text" in seg) return <>{seg.text}</>;
  // A metric chip: the figure is the Python-computed display, never model text.
  return (
    <span
      className="mx-px inline-block rounded-full border border-[var(--adp-accent-ring)] bg-[var(--adp-accent-soft)] px-1.5 py-px text-[12px] font-semibold text-[var(--adp-chip-ink)] tabular-nums"
      title={seg.label}
    >
      {maskFigure(seg.display, units.get(seg.metric), hide)}
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
