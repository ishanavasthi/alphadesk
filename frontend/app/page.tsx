"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
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

  function run(q: string) {
    const trimmed = q.trim();
    if (trimmed) setSubmitted(trimmed);
  }

  if (submitted) {
    return (
      <ResultsDashboard
        query={submitted}
        onReset={() => {
          setSubmitted(null);
          setQuery("");
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
              placeholder="describe what you're hunting for…"
              className="min-w-0 flex-1 bg-transparent font-mono text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
            />
            <Button type="submit" size="sm" disabled={!query.trim()}>
              Run
              <ArrowRight />
            </Button>
          </div>
        </form>

        {/* Sample queries */}
        <div className="mt-3 flex flex-wrap gap-2">
          {SAMPLES.map((s) => (
            <button
              key={s}
              onClick={() => run(s)}
              className="rounded-sm border border-border bg-secondary/40 px-2.5 py-1 text-left font-mono text-[0.7rem] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
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
