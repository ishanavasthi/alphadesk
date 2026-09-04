import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Greeting header (issue #41).
 *
 * A time-of-day greeting with the reader's first name, a static mood line,
 * and a `fetched N ago` timestamp. The four constraints from the issue:
 *
 * 1. IST daypart (hardcoded UTC instants whose IST wall time is asserted).
 * 2. No name reads cleanly — never "Good Afternoon, !".
 * 3. The stamp says "fetched", never "as of".
 * 4. The mood line is static copy keyed to the P&L sign — never a day move,
 *    never a forecast.
 */

import {
  GreetingBlock,
  MOOD_DOWN,
  MOOD_FLAT,
  MOOD_UP,
  daypart,
  fetchedAgo,
  moodLine,
} from "@/components/portfolio/Greeting";

const realTz = process.env.TZ;

describe("daypart (IST)", () => {
  it("follows Asia/Kolkata, not the viewer or the server", () => {
    // 00:00Z = 05:30 IST, 06:00Z = 11:30 IST, 07:00Z = 12:30 IST,
    // 12:00Z = 17:30 IST, 18:30Z = 00:00 IST (midnight folds to morning).
    expect(daypart(new Date("2026-09-03T00:00:00Z"))).toBe("morning");
    expect(daypart(new Date("2026-09-03T06:00:00Z"))).toBe("morning");
    expect(daypart(new Date("2026-09-03T07:00:00Z"))).toBe("afternoon");
    expect(daypart(new Date("2026-09-03T12:00:00Z"))).toBe("evening");
    expect(daypart(new Date("2026-09-03T18:30:00Z"))).toBe("morning");
  });
});

describe("fetchedAgo", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    process.env.TZ = realTz;
  });

  it("renders relative time, never an absolute stamp", () => {
    const now = new Date("2026-09-03T12:00:00+05:30");
    vi.setSystemTime(now);
    expect(fetchedAgo(new Date(now.getTime() - 10_000).toISOString(), now)).toBe("just now");
    expect(fetchedAgo(new Date(now.getTime() - 5 * 60_000).toISOString(), now)).toBe(
      "5 min ago",
    );
    expect(fetchedAgo(new Date(now.getTime() - 3 * 3_600_000).toISOString(), now)).toBe(
      "3 hr ago",
    );
    expect(fetchedAgo(new Date(now.getTime() - 2 * 86_400_000).toISOString(), now)).toBe(
      "2 days ago",
    );
    expect(fetchedAgo(new Date(now.getTime() - 1 * 86_400_000).toISOString(), now)).toBe(
      "1 day ago",
    );
  });
});

describe("moodLine", () => {
  const noon = new Date("2026-09-03T06:30:00Z"); // 12:00 IST

  it("keys off the P&L sign and is deterministic per day", () => {
    expect([...MOOD_UP, ...MOOD_FLAT]).toContain(moodLine(12.5, noon));
    expect([...MOOD_DOWN, ...MOOD_FLAT]).toContain(moodLine(-3, noon));
    expect(MOOD_FLAT).toContain(moodLine(null, noon));
    expect(MOOD_FLAT).toContain(moodLine(0, noon));
    expect(moodLine(9, noon)).toBe(moodLine(9, noon));
  });
});

describe("GreetingBlock", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const noonIST = new Date("2026-09-03T06:30:00Z");

  it("greets by name when there is one", () => {
    vi.setSystemTime(noonIST);
    render(
      <GreetingBlock
        name="Ishan"
        asOf={new Date(noonIST.getTime() - 240_000).toISOString()}
        pnl={10}
        demo={false}
      />,
    );
    expect(screen.getByText("Good afternoon, Ishan.")).toBeTruthy();
    expect(screen.getByText(/Linked account snapshot · fetched 4 min ago/)).toBeTruthy();
  });

  it("reads cleanly with no name and never says 'as of'", () => {
    vi.setSystemTime(noonIST);
    const { container } = render(
      <GreetingBlock
        name={null}
        asOf={new Date(noonIST.getTime() - 30_000).toISOString()}
        pnl={null}
        demo
      />,
    );
    expect(screen.getByText("Good afternoon.")).toBeTruthy();
    expect(screen.getByText(/Invented demo portfolio · fetched just now/)).toBeTruthy();
    expect(container.textContent).not.toMatch(/as of/i);
    // No dangling comma where the name would have been.
    expect(screen.getByRole("heading").textContent).not.toContain(",");
  });
});
