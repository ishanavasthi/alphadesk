import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { RecommendationCard } from "@/components/lab/RecommendationCard";
import type { AnalystRecommendation, RiskAssessment } from "@/lib/api";

/**
 * Honest presentation of the Lab's confidence number (card B11, phase 4).
 *
 * The number is an LLM self-report of *directional* conviction, not a quality
 * score and not a calibrated probability — B11 phase 0 measured it landing in
 * one narrow band regardless of the stock. Drawn alone as a filled bar labelled
 * "Confidence", it read as "how good is this pick". These tests pin the two
 * things that stop it reading that way: the bar is labelled as conviction and
 * described as a self-assessment, and the evidence number is drawn beside it.
 */
const REC: AnalystRecommendation = {
  symbol: "RELIANCE",
  action: "buy",
  confidence: 0.58,
  evidence_quality: 0.2,
  data_gaps: ["earnings", "valuation multiples"],
  bull_thesis: "Bull case.",
  bear_thesis: "Bear case.",
  key_risks: [],
  catalysts: [],
  citations: [],
};

const RISK: RiskAssessment = {
  symbol: "RELIANCE",
  approved: true,
  decision: "FLAG",
  confidence: 0.58,
  evidence_quality: 0.2,
  violations: [],
  flags: ["thin_evidence"],
};

describe("confidence presentation", () => {
  it("labels the bar as conviction, not as a quality score", () => {
    render(<RecommendationCard rec={REC} risk={RISK} />);
    expect(screen.getByText("Conviction")).toBeTruthy();
    expect(screen.queryByText("Confidence")).toBeNull();
  });

  it("says in the open that the number is a self-assessment", () => {
    render(<RecommendationCard rec={REC} risk={RISK} />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("self-assessment");
    expect(text).toContain("not a calibrated probability");
  });

  it("draws the evidence number beside the conviction number", () => {
    render(<RecommendationCard rec={REC} risk={RISK} />);
    expect(screen.getByText("Evidence")).toBeTruthy();
    expect(screen.getByText("58%")).toBeTruthy();
    expect(screen.getByText("20%")).toBeTruthy();
  });

  it("surfaces the gaps the analyst named rather than hiding them", () => {
    render(<RecommendationCard rec={REC} risk={RISK} />);
    expect(screen.getByText("Data gaps")).toBeTruthy();
    expect(screen.getByText("earnings")).toBeTruthy();
  });

  it("explains a FLAG by naming the caution behind it", () => {
    render(<RecommendationCard rec={REC} risk={RISK} />);
    expect(document.body.textContent).toContain("rests on very little data");
  });

  it("omits the evidence bar on older runs that never reported one", () => {
    const legacy = { ...REC, evidence_quality: null, data_gaps: undefined };
    render(<RecommendationCard rec={legacy} risk={{ ...RISK, evidence_quality: null }} />);
    expect(screen.queryByText("Evidence")).toBeNull();
    // Conviction still renders: the older run is shown, just without the pair.
    expect(screen.getByText("Conviction")).toBeTruthy();
    expect(screen.getByText("58%")).toBeTruthy();
  });
});
