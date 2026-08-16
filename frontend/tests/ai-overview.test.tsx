import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { OverviewComplete, OverviewHandlers } from "@/lib/api";

/**
 * The AI overview panel (card A1).
 *
 * Two properties are pinned, and they are the card's whole point:
 *
 * 1. **Degraded is complete.** When the stream ends `degraded` (no model), the
 *    panel says "AI overview unavailable" *and still renders every computed
 *    number* in the metrics rail. The dashboard never depends on the LLM.
 * 2. **Figures come from metrics, not prose.** Every narrative metric chip shows
 *    the Python-computed `display` string; the panel never types a number.
 */

// The mock lets each test drive the stream's handlers directly.
let driver: (handlers: OverviewHandlers) => void = () => {};
/** Every `force` flag the panel sent, in call order. */
let forces: (boolean | undefined)[] = [];

vi.mock("@/lib/api", () => ({
  streamOverview: (
    handlers: OverviewHandlers,
    _signal?: AbortSignal,
    options?: { force?: boolean },
  ) => {
    forces.push(options?.force);
    driver(handlers);
    return Promise.resolve();
  },
}));

// ui.tsx pulls in cva/cn only — safe to import after the api mock.
import { AiOverview } from "@/components/portfolio/AiOverview";

const METRICS: OverviewComplete["metrics"] = [
  { key: "net_worth", label: "Net worth", unit: "inr", available: true, display: "₹10,07,655", value: "1007655", text: null, detail: "net of liabilities", signed: false },
  { key: "holdings_count", label: "Holdings", unit: "count", available: true, display: "9", value: "9", text: null, detail: null, signed: false },
  { key: "herfindahl_index", label: "Herfindahl index (holdings)", unit: "ratio", available: true, display: "0.17", value: "0.17", text: null, detail: "moderate", signed: false },
  { key: "wow_networth_delta", label: "1-week Δ net worth", unit: "inr", available: false, display: "—", value: null, text: null, detail: "needs a week of snapshots", signed: false },
];

beforeEach(() => {
  driver = () => {};
  forces = [];
});

describe("AiOverview — degraded path", () => {
  it("renders every computed number and the unavailable notice when the model is down", async () => {
    driver = (h) => {
      h.onStart?.({ status: "running", agents: [] });
      h.onComplete?.({
        status: "degraded",
        degraded: true,
        reason: "llm_unavailable",
        narrative: [],
        scripted: false,
        metrics: METRICS,
        agents: [],
      });
    };

    render(<AiOverview />);

    // The degraded box names the reason (the rail's static note also mentions
    // "AI overview unavailable", so match on the unique reason line here).
    await waitFor(() => expect(screen.getByText(/the model could not be reached/i)).toBeTruthy());
    expect(screen.getAllByText(/AI overview unavailable/i).length).toBeGreaterThanOrEqual(1);
    // Every AVAILABLE computed number is present, unaffected by the missing model.
    expect(screen.getByText("₹10,07,655")).toBeTruthy();
    expect(screen.getByText("9")).toBeTruthy();
    expect(screen.getByText("0.17")).toBeTruthy();
    // The unavailable metric is not shown as a fabricated value.
    expect(screen.queryByText("1-week Δ net worth")).toBeNull();
  });
});

describe("AiOverview — narrative path", () => {
  it("renders metric chips whose figures are the computed displays", async () => {
    driver = (h) => {
      h.onComplete?.({
        status: "complete",
        degraded: false,
        reason: null,
        scripted: false,
        metrics: METRICS,
        agents: [],
        narrative: [
          {
            segments: [
              { text: "This book holds " },
              { metric: "holdings_count", display: "9", label: "Holdings", detail: null, available: true },
              { text: " names, with a Herfindahl index of " },
              { metric: "herfindahl_index", display: "0.17", label: "Herfindahl index (holdings)", detail: "moderate", available: true },
              { text: "." },
            ],
          },
        ],
      });
    };

    render(<AiOverview />);

    await waitFor(() => expect(screen.getByText(/This book holds/)).toBeTruthy());
    // The chips carry the computed displays.
    const chips = screen.getAllByText("9");
    expect(chips.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("0.17").length).toBeGreaterThanOrEqual(1);
    // Provenance line is present.
    expect(screen.getByText(/computed in Python/i)).toBeTruthy();
  });
});

/**
 * Cached mode — the dashboard's back button.
 *
 * The `/portfolio` route layout keeps the last completed run, so walking to
 * Holdings and returning re-reads it. Re-streaming there would spend five agents
 * (and the daily budget) restating a paragraph that is already written.
 */
describe("AiOverview — cached mode", () => {
  const COMPLETED: OverviewComplete = {
    status: "complete",
    degraded: false,
    reason: null,
    scripted: false,
    metrics: METRICS,
    agents: [],
    narrative: [{ segments: [{ text: "A run that already happened." }] }],
  };

  it("renders a cached run without streaming, and keeps Regenerate", () => {
    driver = () => {
      throw new Error("cached mode must not open a stream");
    };

    render(<AiOverview cached={COMPLETED} onComplete={() => {}} />);

    expect(screen.getByText("A run that already happened.")).toBeTruthy();
    // Unlike /demo's frozen `initial`, the run is over — not unrepeatable.
    expect(screen.getByLabelText(/Regenerate the AI overview/i)).toBeTruthy();
  });

  it("hands a live run back to its caller so the next visit can reuse it", async () => {
    const kept = vi.fn();
    driver = (h) => {
      h.onComplete?.(COMPLETED);
    };

    render(<AiOverview onComplete={kept} />);

    await waitFor(() => expect(kept).toHaveBeenCalledWith(COMPLETED));
  });
});

/**
 * The daily narrative (issue #14) — Regenerate is the only new spend.
 *
 * A mount asks for whatever the backend already wrote today; only the button
 * asks it to write again. Sending `force` on mount would make the "once a day"
 * rule cost a run on every page load, which is the bug this pins shut.
 */
describe("AiOverview — force", () => {
  const COMPLETED: OverviewComplete = {
    status: "complete",
    degraded: false,
    reason: null,
    scripted: false,
    metrics: METRICS,
    agents: [],
    narrative: [{ segments: [{ text: "Today's overview." }] }],
  };

  it("streams without force on mount and with force from Regenerate", async () => {
    driver = (h) => {
      h.onComplete?.(COMPLETED);
    };

    render(<AiOverview />);
    await waitFor(() => expect(forces.length).toBeGreaterThanOrEqual(1));
    expect(forces.every((f) => !f)).toBe(true);

    const before = forces.length;
    fireEvent.click(screen.getByLabelText(/Regenerate the AI overview/i));
    await waitFor(() => expect(forces.length).toBeGreaterThan(before));
    expect(forces[forces.length - 1]).toBe(true);
  });
});
