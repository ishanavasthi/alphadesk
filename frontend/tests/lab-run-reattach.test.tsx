/**
 * The Lab's re-attach banner (issue #17).
 *
 * Starting a run and walking off to `/portfolio` used to lose it: the desk kept
 * the run only in React state, so coming back rendered an empty query box and
 * the run — in flight or finished, waiting for approval — was unreachable
 * without the URL. The fix is one remembered id per tab plus a banner that
 * offers it back.
 *
 * Three behaviours are worth pinning, and all three are about *not* lying to the
 * user: a live run is offered, a run the backend has lost is silently dropped
 * (Lab runs are in-memory by design — card F4 — so this is normal, not an
 * error), and Clear means cleared.
 *
 * `@/lib/api` is mocked because the thing under test is the branch taken, not
 * the fetch.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResumeRunCard, readLabRun, rememberLabRun } from "@/components/ResumeRunCard";

const getRunStatus = vi.fn();

vi.mock("@/lib/api", () => ({
  getRunStatus: (id: string) => getRunStatus(id),
}));

function runningRun(id: string) {
  return {
    run_id: id,
    status: "running",
    query: "oversold pharma large-caps",
    action_id: null,
    awaiting_approval: false,
    next: [],
    state: {},
  };
}

afterEach(() => {
  sessionStorage.clear();
  getRunStatus.mockReset();
});

describe("the Lab re-attach banner", () => {
  it("offers the remembered run, linking to its analysis view", async () => {
    rememberLabRun("run-1234abcd-ef");
    getRunStatus.mockResolvedValue(runningRun("run-1234abcd-ef"));

    render(<ResumeRunCard />);

    await waitFor(() => screen.getByText(/in progress/i));
    const link = document.querySelector('a[href="/lab/a/run-1234abcd-ef"]');
    expect(link).not.toBeNull();
    expect(screen.getByText(/oversold pharma large-caps/)).toBeTruthy();
  });

  it("drops the id and shows nothing when the run is gone (backend restart)", async () => {
    rememberLabRun("stale-run");
    getRunStatus.mockRejectedValue(new Error("not_found"));

    const { container } = render(<ResumeRunCard />);

    await waitFor(() => expect(readLabRun()).toBeNull());
    expect(container.textContent).toBe("");
  });

  it("renders nothing, and asks the backend nothing, with no remembered run", () => {
    const { container } = render(<ResumeRunCard />);
    expect(container.textContent).toBe("");
    expect(getRunStatus).not.toHaveBeenCalled();
  });

  it("forgets the run, and hides the banner, on Clear", async () => {
    rememberLabRun("run-to-clear");
    getRunStatus.mockResolvedValue(runningRun("run-to-clear"));

    const { container } = render(<ResumeRunCard />);
    const clear = await screen.findByLabelText("Clear remembered run");

    fireEvent.click(clear);

    expect(readLabRun()).toBeNull();
    expect(container.textContent).toBe("");
  });
});
