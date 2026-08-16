import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import LabLayout from "@/app/lab/layout";

/**
 * The Lab's persistent "simulation — not investment advice" label (card F4).
 *
 * The Lab produces buy/avoid calls with confidence scores, which read like
 * advice unless the surface says otherwise on *every* view. The label lives in
 * `app/lab/layout.tsx` so no page under `/lab` can render without it — this test
 * pins that it is there and that it names the two things that matter: this is a
 * simulation, and no orders are placed / it is not advice.
 *
 * The layout also renders the terminal `<TopBar/>` and wraps itself in
 * `<AuthProvider>` as of card U1 (which retired the app-wide `TerminalChrome`
 * and scoped the IND Money provider to the surfaces that read it). `fetch` is
 * stubbed so the provider's warm-up ping stays offline instead of reaching for a
 * real backend.
 */
describe("the Lab label", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline in test"))));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders on the Lab layout, wrapping the page", () => {
    render(
      <LabLayout>
        <main>desk</main>
      </LabLayout>,
    );

    const label = document.querySelector("[data-lab-label]");
    expect(label).not.toBeNull();
    const text = label?.textContent?.toLowerCase() ?? "";
    expect(text).toContain("simulation");
    expect(text).toContain("not investment advice");
    expect(text).toContain("no orders");
    // The children still render — the label is a banner, not a replacement.
    expect(screen.getByText("desk")).toBeTruthy();
  });
});
