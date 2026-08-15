import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { StalenessBanner } from "@/components/portfolio/StalenessBanner";
import {
  attributedDay,
  lastExpectedDay,
  staleness,
  stalenessMessage,
} from "@/components/portfolio/staleness";

/**
 * The staleness banner: fresh, stale, never-captured.
 *
 * This is the surface that notices when the nightly job has silently stopped —
 * an expired secret, a renamed Space, or GitHub's 60-day scheduled-workflow
 * disable, none of which announce themselves. The date rule it depends on is
 * the same 06:00-IST cutoff the backend files snapshots with
 * (`backend/services/snapshots.py`), so it is asserted here in the same terms
 * `backend/tests/test_snapshots.py` asserts it there.
 */

/** 2026-08-16 15:00 IST — mid-afternoon, well clear of the cutoff. */
const NOW = new Date("2026-08-16T09:30:00Z");

const at = (iso: string) => new Date(iso);

describe("attributedDay", () => {
  it("files 23:45 IST under that day and 01:00 IST under the previous one", () => {
    // 18:15Z = 23:45 IST on the 16th.
    expect(attributedDay(at("2026-08-16T18:15:00Z"))).toBe("2026-08-16");
    // 19:30Z = 01:00 IST on the 17th — before the cutoff, so still the 16th.
    expect(attributedDay(at("2026-08-16T19:30:00Z"))).toBe("2026-08-16");
  });

  it("switches day at exactly 06:00 IST", () => {
    // 00:29Z = 05:59 IST on the 17th.
    expect(attributedDay(at("2026-08-17T00:29:00Z"))).toBe("2026-08-16");
    // 00:30Z = 06:00 IST on the 17th.
    expect(attributedDay(at("2026-08-17T00:30:00Z"))).toBe("2026-08-17");
  });

  it("does not depend on the reader's local timezone", () => {
    // Same instant, three notations. A helper reading local fields would drift.
    const instant = "2026-08-16T18:15:00Z";
    expect(attributedDay(at(instant))).toBe(attributedDay(at("2026-08-16T23:45:00+05:30")));
    expect(attributedDay(at(instant))).toBe(attributedDay(at("2026-08-16T13:15:00-05:00")));
  });

  it("shifts into IST, not merely applies the cutoff to UTC", () => {
    // Neither scheduled run discriminates on its own — both fall the same side
    // of the IST and UTC cutoffs. These two do, and between them they kill both
    // wrong implementations:
    //   02:00Z is 07:30 IST, past the cutoff -> the 16th. UTC + the same cutoff
    //   sees hour 2 and answers the 15th.
    expect(attributedDay(at("2026-08-16T02:00:00Z"))).toBe("2026-08-16");
    //   00:15Z is 05:45 IST, before it -> the 15th. A plain UTC date says 16th.
    expect(attributedDay(at("2026-08-16T00:15:00Z"))).toBe("2026-08-15");
  });

  it("expects yesterday, because today's own capture may not have run yet", () => {
    expect(lastExpectedDay(NOW)).toBe("2026-08-15");
  });
});

describe("staleness", () => {
  it("is `never` when nothing has been captured", () => {
    expect(staleness(null, NOW)).toEqual({ kind: "never" });
    expect(staleness(undefined, NOW)).toEqual({ kind: "never" });
  });

  it("treats an unreadable timestamp as `never`, not as stale", () => {
    // Diagnosing "history paused" from a value we could not parse would be
    // inventing a fault.
    expect(staleness("not-a-date", NOW)).toEqual({ kind: "never" });
  });

  it("is fresh for last night's capture", () => {
    // 2026-08-15 23:45 IST.
    expect(staleness("2026-08-15T18:15:00Z", NOW)).toEqual({
      kind: "fresh",
      capturedOn: "2026-08-15",
    });
  });

  it("is fresh for a capture that already landed today", () => {
    expect(staleness("2026-08-16T18:15:00Z", NOW).kind).toBe("fresh");
  });

  it("is stale once a full expected day has been missed", () => {
    expect(staleness("2026-08-14T18:15:00Z", NOW)).toEqual({
      kind: "stale",
      capturedOn: "2026-08-14",
      days: 2,
    });
  });

  it("counts the gap in attributed days, not in elapsed hours", () => {
    const state = staleness("2026-08-01T18:15:00Z", NOW);
    expect(state).toMatchObject({ kind: "stale", days: 15 });
  });

  it("classifies every gap, and never reports a stale gap of one day", () => {
    // Asserted unconditionally in both directions, so a classifier that simply
    // stopped emitting "stale" would fail here rather than pass vacuously —
    // which a `if (state.kind === "stale")` guard would have let it do.
    //
    // A one-day gap is exactly the grace the cutoff buys (today's own capture
    // runs at 23:45 IST), so the smallest honest complaint is two. "1 days ago"
    // would be both wrong and ungrammatical.
    for (let offset = 0; offset < 40; offset += 1) {
      const captured = new Date(NOW.getTime() - offset * 86_400_000);
      const state = staleness(captured.toISOString(), NOW);
      if (offset <= 1) {
        expect(state.kind).toBe("fresh");
      } else {
        expect(state.kind).toBe("stale");
        expect(state).toMatchObject({ days: offset });
        expect(state.kind === "stale" && state.days).toBeGreaterThanOrEqual(2);
      }
    }
  });
});

describe("stalenessMessage", () => {
  it("says nothing when fresh or never captured", () => {
    expect(stalenessMessage({ kind: "fresh", capturedOn: "2026-08-15" })).toBeNull();
    expect(stalenessMessage({ kind: "never" })).toBeNull();
  });

  it("names the gap and the day", () => {
    expect(stalenessMessage({ kind: "stale", capturedOn: "2026-08-14", days: 2 })).toBe(
      "History paused — last captured 2 days ago (2026-08-14).",
    );
  });
});

describe("<StalenessBanner/>", () => {
  it("renders nothing when the history is fresh", () => {
    const { container } = render(
      <StalenessBanner lastCapturedAt="2026-08-15T18:15:00Z" now={NOW} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when nothing has ever been captured", () => {
    // The trend card's own empty state covers this; two messages about the same
    // absence would read as a fault rather than a beginning.
    const { container } = render(<StalenessBanner lastCapturedAt={null} now={NOW} />);
    expect(container.innerHTML).toBe("");
  });

  it("warns, names the gap, and says the missed days are gone", () => {
    render(<StalenessBanner lastCapturedAt="2026-08-10T18:15:00Z" now={NOW} />);
    expect(screen.getByText(/History paused — last captured 6 days ago/)).toBeTruthy();
    expect(screen.getByText(/cannot be recovered/)).toBeTruthy();
  });
});
