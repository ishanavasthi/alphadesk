"use client";

import { useState } from "react";
import { ArrowRight, KeyRound, Loader2, Plug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/AuthProvider";
import { ResultsDashboard } from "@/components/ResultsDashboard";

const SAMPLES = [
  "find me momentum stocks in IT sector",
  "oversold pharma large-caps with a catalyst",
  "high implied-volatility option setups this week",
];

const PIPELINE = ["SCAN", "RESEARCH", "ANALYSE", "RISK", "EXECUTE"];

export default function Home() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const { authed, busy, connect } = useAuth();

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
          if (typeof window !== "undefined") window.history.replaceState(null, "", "/");
        }}
      />
    );
  }

  return (
    <main className="hero-glow">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-3xl flex-col justify-center px-4 py-16 sm:px-6">
        <div className="eyebrow mb-4">Multi-agent equity research</div>
        <h1 className="text-4xl font-semibold leading-[1.05] tracking-tight sm:text-5xl">
          Type a thesis.
          <br />
          <span className="text-primary">The desk does the legwork.</span>
        </h1>
        <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Five agents scan the NSE, research each candidate, write the call, and
          enforce risk guardrails. Nothing reaches your watchlist without your sign-off.
        </p>

        {/* Command-line search */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(query);
          }}
          className="mt-8"
        >
          <div className="flex items-center gap-2 border border-border bg-card px-3 py-3 focus-within:border-primary/60 focus-within:ring-1 focus-within:ring-primary/30">
            <span className="select-none font-mono text-sm font-semibold text-primary">
              query{">"}
            </span>
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={!connected}
              placeholder={
                connected
                  ? "describe what you're hunting for…"
                  : "connect IND Money to run a query…"
              }
              className="min-w-0 flex-1 bg-transparent font-mono text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
            />
            <Button type="submit" size="sm" disabled={!query.trim() || !connected}>
              Run
              <ArrowRight />
            </Button>
          </div>
        </form>

        {/* Connection gate — the desk has no market data until IND Money is linked */}
        {!connected && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border border-border border-l-2 border-l-flag bg-card p-3">
            <div className="flex items-start gap-2.5">
              <span className="text-flag">
                {checking ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plug className="h-4 w-4" />
                )}
              </span>
              <div>
                <div className="eyebrow text-flag">
                  {checking ? "Checking IND Money connection" : "IND Money not connected"}
                </div>
                <div className="mt-0.5 text-[0.8rem] text-muted-foreground">
                  {checking
                    ? "Confirming the backend still holds a valid session…"
                    : "Every agent reads NSE data through the IND Money MCP. Connect it first, or the scan returns 0 candidates."}
                </div>
              </div>
            </div>
            {!checking && (
              <Button size="sm" onClick={connect} disabled={busy}>
                {busy ? <Loader2 className="animate-spin" /> : <KeyRound />}
                Connect IND Money
              </Button>
            )}
          </div>
        )}

        {/* Sample queries */}
        <div className="mt-3 flex flex-wrap gap-2">
          {SAMPLES.map((s) => (
            <button
              key={s}
              onClick={() => run(s)}
              disabled={!connected}
              className="rounded-sm border border-border bg-secondary/40 px-2.5 py-1 text-left font-mono text-[0.7rem] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-border disabled:hover:text-muted-foreground"
            >
              {s}
            </button>
          ))}
        </div>

        {/* Static pipeline preview tape */}
        <div className="mt-12 flex items-center gap-2 border-t border-border pt-5">
          <span className="eyebrow mr-1">Pipeline</span>
          {PIPELINE.map((p, i) => (
            <span key={p} className="flex items-center gap-2">
              <span className="font-mono text-[0.7rem] tracking-[0.1em] text-muted-foreground">
                {p}
              </span>
              {i < PIPELINE.length - 1 && (
                <span className="text-border">▸</span>
              )}
            </span>
          ))}
        </div>
      </div>
    </main>
  );
}
