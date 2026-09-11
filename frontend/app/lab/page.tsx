"use client";

import { useState } from "react";
import { ArrowRight, KeyRound, Loader2 } from "lucide-react";

import { useIndMoney } from "@/components/AuthProvider";
import { ResultsDashboard } from "@/components/lab/ResultsDashboard";
import { ResumeRunCard } from "@/components/lab/ResumeRunCard";
import { Button, Card, EmptyCallout } from "@/components/ui/adp";

const SAMPLES = [
  "find me momentum stocks in IT sector",
  "oversold pharma large-caps with a catalyst",
  "high implied-volatility option setups this week",
];

/** The agents, in the order they consume one another. */
const PIPELINE = ["Scanner", "Research", "Analyst", "Risk Manager", "Execution"];

export default function LabHome() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const { authed, busy, connect } = useIndMoney();

  // Every agent is fed by the IND Money MCP, so a query run while logged out can
  // only return an empty "0 candidates" pipeline. Gate the form instead.
  const connected = authed === true;
  const checking = authed === null;

  function run(q: string) {
    const trimmed = q.trim();
    if (trimmed && connected) setSubmitted(trimmed);
  }

  if (submitted) {
    return (
      <ResultsDashboard
        query={submitted}
        onReset={() => {
          setSubmitted(null);
          setQuery("");
          if (typeof window !== "undefined") window.history.replaceState(null, "", "/lab");
        }}
      />
    );
  }

  return (
    <main className="mt-8 max-w-2xl">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">
        Type a thesis. The desk does the legwork.
      </h1>
      <p className="mt-1.5 text-[13px] text-muted-foreground">
        Five agents read live NSE data, research each candidate, write the call and enforce the
        risk guardrails. Nothing reaches your watchlist without your sign-off.
      </p>

      <Card className="mt-5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(query);
          }}
          className="flex flex-wrap gap-2"
        >
          <label htmlFor="lab-query" className="sr-only">
            What are you hunting for?
          </label>
          <input
            id="lab-query"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={!connected}
            placeholder={
              connected
                ? "describe what you’re hunting for…"
                : "connect IND Money to run a query…"
            }
            className="min-w-[12rem] flex-1 rounded-md border border-border bg-card px-3 py-2 text-[13px] text-foreground transition-colors placeholder:text-[var(--adp-faint)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
          />
          <Button type="submit" variant="primary" disabled={!query.trim() || !connected}>
            Run
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </form>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {SAMPLES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => run(s)}
              disabled={!connected}
              className="rounded-full border border-border bg-card px-3 py-1 text-left text-xs text-muted-foreground transition-colors hover:border-[var(--adp-accent-ring)] hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-border disabled:hover:text-muted-foreground"
            >
              {s}
            </button>
          ))}
        </div>

        {/* The pipeline, before there is a run to show in it. Order is the real
            dependency chain, so it previews what the strip will say. */}
        <div className="mt-5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-[var(--adp-hairline)] pt-3.5 text-xs text-muted-foreground">
          <span className="text-[var(--adp-faint)]">Pipeline</span>
          {PIPELINE.map((p, i) => (
            <span key={p} className="flex items-center gap-2">
              {p}
              {i < PIPELINE.length - 1 ? (
                <span className="text-[var(--adp-faint)]" aria-hidden>
                  →
                </span>
              ) : null}
            </span>
          ))}
        </div>
      </Card>

      {/* Re-attach: a run started in this session survives a trip to /portfolio */}
      <ResumeRunCard />

      {/* Connection gate — the desk has no market data until IND Money is linked */}
      {!connected ? (
        <div className="mt-4 flex flex-col gap-3">
          <EmptyCallout icon={checking ? "◌" : "⚿"}>
            {checking ? (
              <>
                <b className="font-semibold text-foreground">
                  Checking your IND Money connection.
                </b>{" "}
                Confirming the backend still holds a valid session…
              </>
            ) : (
              <>
                <b className="font-semibold text-foreground">IND Money isn’t connected.</b> Every
                agent reads NSE data through it — without a link the scan returns 0 candidates.
              </>
            )}
          </EmptyCallout>
          {!checking ? (
            <div>
              <Button variant="accent" onClick={connect} disabled={busy}>
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <KeyRound className="h-3.5 w-3.5" />
                )}
                Connect IND Money
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}
