/**
 * The privacy toggle: hide every rupee amount on the portfolio surface.
 *
 * Three things here are easy to get wrong and are therefore the whole point of
 * this file:
 *
 * 1. **A masked number must not look like a missing one.** `—` means the source
 *    never reported the figure; a dot run means the reader chose to hide it.
 *    Collapsing the two would make the toggle lie about the data.
 * 2. **Units are part of the secret.** A holding's price is public, so units
 *    left visible multiply straight back into the position value.
 * 3. **The AI overview does not go through `format.ts`.** Its figures are strings
 *    rendered by the backend, so the mask has to be enforced a second time in
 *    that panel — the exact place a formatter-level fix would silently miss.
 */

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OverviewComplete } from "@/lib/api";

// The panel opens a stream on mount unless it is handed a cached run; the cached
// path is the one under test, so the stream must never be reached.
vi.mock("@/lib/api", () => ({
  streamPortfolioOverview: () => {
    throw new Error("cached mode must not open a stream");
  },
}));

import { AiOverview } from "@/components/portfolio/AiOverview";
import { PrivacyToggle } from "@/components/portfolio/PrivacyToggle";
import { inr, inrSigned, lakh, pct, pctSigned, units } from "@/components/portfolio/format";
import {
  resetPrivacy,
  setAmountsHidden,
  toggleAmountsHidden,
} from "@/components/portfolio/privacy";

// jsdom in this runner exposes no `window.localStorage`, and the module treats a
// throwing storage as "no choice" — which would let the persistence assertions
// pass for the wrong reason. Same in-memory stand-in the theme tests use.
const store = new Map<string, string>();
Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => void store.set(key, String(value)),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
    key: (index: number) => [...store.keys()][index] ?? null,
    get length() {
      return store.size;
    },
  },
});

beforeEach(() => resetPrivacy());
afterEach(() => {
  cleanup();
  resetPrivacy();
  store.clear();
});

describe("the formatters mask amounts, and only amounts", () => {
  it("hides rupee figures, units and the chart axis", () => {
    expect(inr(1007655)).toBe("₹10,07,655");
    expect(units(22.5)).toBe("22.5");
    expect(lakh(1007655)).toBe("10.1L");

    setAmountsHidden(true);

    expect(inr(1007655)).toBe("₹••••••");
    // Units are hidden too: price is public, so units × price is the amount.
    expect(units(22.5)).toBe("•••");
    // The trend line keeps its shape; the axis stops naming a balance.
    expect(lakh(1007655)).toBe("•••");
  });

  it("keeps the sign on a masked P&L", () => {
    setAmountsHidden(true);
    expect(inrSigned(88905)).toBe("+₹••••••");
    expect(inrSigned(-1240)).toBe("−₹••••••");
  });

  it("leaves percentages and weights alone", () => {
    setAmountsHidden(true);
    expect(pctSigned(8.4)).toBe("+8.4%");
    expect(pct(24.2)).toBe("24.2%");
  });

  it("still renders a missing number as —, not as a mask", () => {
    setAmountsHidden(true);
    // "the source did not report this" and "I chose to hide this" are different
    // facts. `null` must survive masking as its own glyph.
    expect(inr(null)).toBe("—");
    expect(inrSigned(null)).toBe("—");
    expect(units(null)).toBe("—");
  });
});

describe("the choice persists", () => {
  it("writes the flip to localStorage", () => {
    toggleAmountsHidden();
    expect(window.localStorage.getItem("adp-privacy")).toBe("on");
    toggleAmountsHidden();
    expect(window.localStorage.getItem("adp-privacy")).toBe("off");
  });

  it("comes back hidden on a fresh load", async () => {
    window.localStorage.setItem("adp-privacy", "on");
    // A fresh module registry is this runner's stand-in for a page load: the
    // flag is read once at import, before the first render that could contain a
    // number, which is what makes the no-flash claim true.
    vi.resetModules();
    const fresh = await import("@/components/portfolio/format");
    expect(fresh.inr(1007655)).toBe("₹••••••");
  });
});

describe("the button", () => {
  it("offers the action it depicts and announces the state", () => {
    render(<PrivacyToggle />);

    const button = screen.getByRole("button");
    expect(button.getAttribute("aria-label")).toBe("Hide amounts");
    expect(button.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(button);

    expect(button.getAttribute("aria-label")).toBe("Show amounts");
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(inr(1007655)).toBe("₹••••••");
  });
});

const COMPLETED: OverviewComplete = {
  status: "complete",
  degraded: false,
  reason: null,
  scripted: false,
  agents: [],
  metrics: [
    {
      key: "net_worth",
      label: "Net worth",
      unit: "inr",
      available: true,
      display: "₹10,07,655",
      value: "1007655",
      text: null,
      detail: "net of liabilities",
      signed: false,
    },
    {
      key: "equity_share",
      label: "Equity share",
      unit: "pct",
      available: true,
      display: "62.4%",
      value: "62.4",
      text: null,
      detail: "Indian + US equity",
      signed: false,
    },
  ],
  narrative: [
    {
      segments: [
        { text: "Your portfolio stands at " },
        {
          metric: "net_worth",
          display: "₹10,07,655",
          label: "Net worth",
          detail: null,
          available: true,
        },
        { text: " with " },
        {
          metric: "equity_share",
          display: "62.4%",
          label: "Equity share",
          detail: null,
          available: true,
        },
        { text: " in equity." },
      ],
    },
  ],
};

describe("the AI overview is masked too", () => {
  it("hides rupee figures in the narrative chips and the metrics rail", () => {
    render(<AiOverview cached={COMPLETED} onComplete={() => {}} />);

    // Two live renderings of the same backend string: the inline chip and the
    // rail row. Both are real, so both must go.
    expect(screen.getAllByText("₹10,07,655").length).toBe(2);

    act(() => setAmountsHidden(true));

    expect(screen.queryByText("₹10,07,655")).toBeNull();
    expect(screen.getAllByText("₹••••••").length).toBe(2);
    // The percentage metric is untouched — chip and rail alike.
    expect(screen.getAllByText("62.4%").length).toBe(2);
    // Labels stay: hiding the figure should not hide what it was about.
    expect(screen.getByText("Net worth")).toBeTruthy();
  });
});
