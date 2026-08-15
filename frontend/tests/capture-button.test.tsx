import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  PortfolioTopBar,
  type CaptureState,
} from "@/components/portfolio/PortfolioTopBar";

/**
 * The Capture button's vocabulary.
 *
 * Every state here is a sentence the reader is asked to believe about their own
 * data, so the mapping is pinned rather than eyeballed. In particular
 * `in_flight` is **not** a failure: opening the dashboard starts a capture when
 * today's row is missing, so pressing the button a second later legitimately
 * finds one running, and saying "failed" would send someone looking for a
 * problem that does not exist.
 */

function bar(captureState: CaptureState) {
  return render(
    <PortfolioTopBar
      linkHealth="linked"
      demo={false}
      onRefresh={() => {}}
      refreshing={false}
      cooldown={0}
      onCapture={() => {}}
      captureState={captureState}
    />,
  );
}

const CASES: Array<[CaptureState, string]> = [
  ["idle", "Capture snapshot"],
  ["busy", "Capturing…"],
  ["done", "Captured"],
  ["existing", "Already captured today"],
  ["in_flight", "Capturing in background…"],
  ["failed", "Capture failed"],
];

describe("<PortfolioTopBar/> capture button", () => {
  it.each(CASES)("says the right thing in %s", (state, label) => {
    bar(state);
    expect(screen.getByRole("button", { name: new RegExp(label) })).toBeTruthy();
  });

  it("never calls a background capture a failure", () => {
    bar("in_flight");
    expect(screen.queryByRole("button", { name: /failed/i })).toBeNull();
  });

  it("is disabled only while this page's own capture is running", () => {
    for (const [state, label] of CASES) {
      const view = bar(state);
      const button = screen.getByRole("button", { name: new RegExp(label) });
      expect((button as HTMLButtonElement).disabled).toBe(state === "busy");
      view.unmount();
    }
  });

  it("no longer advertises itself as unfinished work", () => {
    // D1 shipped this button disabled with a `soon` badge reading "S1". S1 is
    // this card; the badge going stale would be a promise nobody kept.
    bar("idle");
    expect(screen.queryByText("S1")).toBeNull();
  });
});
