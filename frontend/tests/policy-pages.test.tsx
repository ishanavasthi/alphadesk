/**
 * The privacy and terms pages carry the real L1 content (card L1).
 *
 * Acceptance: the policy pages name **both LLM providers** (Groq + OpenAI) and
 * the other subprocessors, state the no-orders / not-advice framing, and the
 * footer that links them renders Privacy + Terms on every page that uses it.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PrivacyPage from "@/app/(marketing)/privacy/page";
import TermsPage from "@/app/(marketing)/terms/page";
import { PortfolioFooter } from "@/components/portfolio/ui";

describe("privacy policy", () => {
  it("names every subprocessor, both LLM providers included", () => {
    render(<PrivacyPage />);
    for (const name of ["Groq", "OpenAI", "Clerk", "Neon", "Hugging Face", "Vercel"]) {
      expect(screen.getAllByText(new RegExp(name)).length).toBeGreaterThan(0);
    }
  });

  it("states retention: snapshots kept, raw payloads pruned at 90 days", () => {
    render(<PrivacyPage />);
    expect(screen.getByText(/pruned after 90 days/i)).toBeTruthy();
  });

  it("describes deleting data: revoke upstream first, then cascade", () => {
    render(<PrivacyPage />);
    expect(screen.getByText(/revokes your broker token upstream/i)).toBeTruthy();
  });
});

describe("terms", () => {
  it("states no orders are ever placed and it is not advice", () => {
    render(<TermsPage />);
    expect(screen.getAllByText(/No real orders are ever placed/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/not investment advice/i).length).toBeGreaterThan(0);
  });
});

describe("footer", () => {
  it("links Privacy and Terms", () => {
    const { container } = render(<PortfolioFooter demo={false} />);
    const footer = within(container);
    expect(footer.getByText("Privacy").getAttribute("href")).toBe("/privacy");
    expect(footer.getByText("Terms").getAttribute("href")).toBe("/terms");
  });
});
