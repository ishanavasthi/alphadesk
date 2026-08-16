/**
 * Disconnecting IND Money from the dashboard (issue #13).
 *
 * Two things are pinned. The chip that reports the link is the control that
 * ends it — nothing happens until the confirm dialog is answered. And the
 * closing copy is honest: when the backend says the grant survived upstream,
 * the user is told to remove it on IND Money's side rather than being handed a
 * clean "disconnected" that is only half true.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { unlinkIndMoney } = vi.hoisted(() => ({
  unlinkIndMoney: vi.fn(async () => ({
    status: "unlinked" as const,
    upstream_revoked: true,
  })),
}));

vi.mock("@/lib/api", () => ({ unlinkIndMoney }));

import { PortfolioTopBar } from "@/components/portfolio/PortfolioTopBar";
import { UnlinkDialog } from "@/components/portfolio/UnlinkDialog";

function bar(onRefresh = () => {}) {
  return render(
    <PortfolioTopBar
      linkHealth="linked"
      demo={false}
      onRefresh={onRefresh}
      refreshing={false}
      cooldown={0}
      onCapture={() => {}}
    />,
  );
}

beforeEach(() => {
  unlinkIndMoney.mockClear();
  unlinkIndMoney.mockResolvedValue({ status: "unlinked", upstream_revoked: true });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("unlinking IND Money", () => {
  it("does not disconnect on the chip press alone", () => {
    bar();
    fireEvent.click(screen.getByRole("button", { name: /IND Money · linked/ }));
    expect(screen.getByText(/Disconnect IND Money\?/)).toBeTruthy();
    expect(unlinkIndMoney).not.toHaveBeenCalled();
  });

  it("cancelling leaves the link alone", () => {
    const refresh = vi.fn();
    bar(refresh);
    fireEvent.click(screen.getByRole("button", { name: /IND Money · linked/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(unlinkIndMoney).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("unlinks and reloads the surface, which is what raises the Connect gate", async () => {
    const refresh = vi.fn();
    bar(refresh);
    fireEvent.click(screen.getByRole("button", { name: /IND Money · linked/ }));
    fireEvent.click(screen.getByRole("button", { name: "Unlink" }));

    await waitFor(() => expect(unlinkIndMoney).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it("says so when the grant survived at the source", async () => {
    unlinkIndMoney.mockResolvedValue({ status: "unlinked", upstream_revoked: false });
    const refresh = vi.fn();
    render(<UnlinkDialog open onOpenChange={() => {}} onUnlinked={refresh} />);
    fireEvent.click(screen.getByRole("button", { name: "Unlink" }));

    await screen.findByText(/may still be listed on IND Money's side/);
    // The caveat has to be readable, so the reload waits for the reader.
    expect(refresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("reports a failed disconnect instead of pretending", async () => {
    unlinkIndMoney.mockRejectedValue(new Error("Unlink failed (503)."));
    const refresh = vi.fn();
    render(<UnlinkDialog open onOpenChange={() => {}} onUnlinked={refresh} />);
    fireEvent.click(screen.getByRole("button", { name: "Unlink" }));

    await screen.findByText(/Unlink failed \(503\)\./);
    expect(refresh).not.toHaveBeenCalled();
  });
});
