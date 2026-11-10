import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CandidateSections } from "@/components/lab/CandidateSections";
import type { AnalystRecommendation, RiskAssessment } from "@/lib/api";

/**
 * The Lab's result layout fits the number of calls (the PPLPHARMA run: one
 * cleared call drawn in a third of the row beside two thirds of nothing, with a
 * half-width rejection under it), and its hint follows the sign-off instead of
 * asking for one already given.
 */
function rec(symbol: string, action: AnalystRecommendation["action"] = "hold"): AnalystRecommendation {
  return {
    symbol,
    action,
    confidence: 0.55,
    evidence_quality: 0.15,
    data_gaps: ["earnings"],
    bull_thesis: `${symbol} bull.`,
    bear_thesis: `${symbol} bear.`,
    key_risks: ["risk"],
    catalysts: ["catalyst"],
    citations: [],
  };
}

function risk(symbol: string, approved: boolean): RiskAssessment {
  return {
    symbol,
    approved,
    decision: approved ? "FLAG" : "REJECT",
    confidence: 0.55,
    evidence_quality: 0.15,
    violations: [],
    flags: [],
    notes: `${symbol} notes.`,
  };
}

function grids(container: HTMLElement) {
  return [...container.querySelectorAll("section > div.grid")] as HTMLElement[];
}

describe("candidate sections", () => {
  const recs = [rec("PPLPHARMA"), rec("VIKRAMSOLR", "avoid")];
  const risks = { PPLPHARMA: risk("PPLPHARMA", true), VIKRAMSOLR: risk("VIKRAMSOLR", false) };

  it("gives a lone call the whole row instead of a third of it", () => {
    const { container } = render(<CandidateSections recs={recs} risks={risks} />);
    const [cleared, stopped] = grids(container);
    for (const grid of [cleared, stopped]) {
      expect(grid.className).not.toMatch(/grid-cols-2|grid-cols-3/);
    }
  });

  it("divides the row only as far as there are cards", () => {
    const three = ["A", "B", "C"];
    const { container } = render(
      <CandidateSections
        recs={three.map((s) => rec(s))}
        risks={Object.fromEntries(three.map((s) => [s, risk(s, true)]))}
      />,
    );
    expect(grids(container)[0].className).toContain("lg:grid-cols-3");
  });

  it.each([
    ["awaiting_approval", "One call, awaiting your sign-off"],
    ["completed", "One call, signed off"],
    ["rejected", "One call, declined at sign-off"],
  ] as const)("hint while %s", (status, hint) => {
    render(<CandidateSections recs={recs} risks={risks} status={status} />);
    expect(screen.getByText(hint)).toBeTruthy();
  });

  it("keeps every part of the brief on the wide card", () => {
    render(<CandidateSections recs={recs} risks={risks} status="completed" />);
    for (const text of ["PPLPHARMA bull.", "PPLPHARMA bear.", "Catalysts", "Key risks", "Data gaps", "Target", "Horizon"]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
  });
});
