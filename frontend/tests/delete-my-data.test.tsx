/**
 * The "Delete my data" confirmation (card L1).
 *
 * The button must not fire on a stray click: it arms only after the user types
 * the confirmation word. On confirm it calls `DELETE /account` and then signs
 * the user out.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { deleteAccount, signOut } = vi.hoisted(() => ({
  deleteAccount: vi.fn(async () => ({ deleted: true, user_id: "u", revoked_upstream: true })),
  signOut: vi.fn(async () => undefined),
}));

vi.mock("@/lib/api", () => ({ deleteAccount }));
vi.mock("@clerk/nextjs", () => ({ useClerk: () => ({ signOut }) }));

import { DeleteMyDataDialog } from "@/components/clerk/DeleteMyDataDialog";

beforeEach(() => {
  deleteAccount.mockClear();
  signOut.mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("delete-my-data confirmation", () => {
  it("keeps the delete button disabled until the word is typed", () => {
    render(<DeleteMyDataDialog open onClose={() => {}} />);
    const button = screen.getByText(/Delete everything/i) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Type DELETE to confirm/i), {
      target: { value: "DELETE" },
    });
    expect(button.disabled).toBe(false);
  });

  it("does nothing on the wrong word", () => {
    render(<DeleteMyDataDialog open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText(/Type DELETE to confirm/i), {
      target: { value: "delete please" },
    });
    fireEvent.click(screen.getByText(/Delete everything/i));
    expect(deleteAccount).not.toHaveBeenCalled();
  });

  it("calls DELETE /account and signs out on confirm", async () => {
    render(<DeleteMyDataDialog open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText(/Type DELETE to confirm/i), {
      target: { value: "DELETE" },
    });
    fireEvent.click(screen.getByText(/Delete everything/i));

    await waitFor(() => expect(deleteAccount).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(signOut).toHaveBeenCalledWith({ redirectUrl: "/" }));
  });

  it("renders nothing when closed", () => {
    const { container } = render(<DeleteMyDataDialog open={false} onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
