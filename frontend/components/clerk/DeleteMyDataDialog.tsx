"use client";

import { useClerk } from "@clerk/nextjs";
import { useState } from "react";

import { deleteAccount } from "@/lib/api";

/**
 * The "Delete my data" confirmation (card L1, the DPDP erasure right).
 *
 * Explicit and irreversible, so it asks the user to type the word before the
 * button arms — a one-click destructive action on someone's entire net-worth
 * history is not a thing to leave to a stray tap. On success it revokes the
 * broker grant upstream and cascade-deletes every row (see `DELETE /account`),
 * then signs the user out and returns them to the public site.
 */
const CONFIRM_WORD = "DELETE";

export function DeleteMyDataDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { signOut } = useClerk();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const armed = typed.trim().toUpperCase() === CONFIRM_WORD && !busy;

  const onDelete = async () => {
    if (!armed) return;
    setBusy(true);
    setError(null);
    try {
      await deleteAccount();
      // Sign out and leave the app; their session and data are gone.
      await signOut({ redirectUrl: "/" });
    } catch (err) {
      setError((err as Error).message || "Deletion failed. Please try again.");
      setBusy(false);
    }
  };

  return (
    <div
      role="presentation"
      onClick={busy ? undefined : onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 70,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(3, 5, 8, 0.66)",
        padding: "16px",
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-data-title"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-lg border border-border bg-background p-5 text-foreground shadow-xl"
      >
        <h2 id="delete-data-title" className="text-base font-semibold tracking-[-0.01em]">
          Delete my data
        </h2>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
          This <b className="font-semibold text-foreground">permanently</b> deletes your
          account and everything AlphaDesk stored: your IND Money link (revoked at the source
          first), your daily net-worth snapshots and history, and your paper watchlist. It
          cannot be undone.
        </p>
        <label className="mt-4 block text-[13px] text-muted-foreground">
          Type <b className="font-mono font-semibold text-foreground">{CONFIRM_WORD}</b> to
          confirm:
          <input
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            disabled={busy}
            autoComplete="off"
            aria-label={`Type ${CONFIRM_WORD} to confirm`}
            className="mt-1.5 w-full rounded-md border border-border bg-transparent px-3 py-1.5 text-[13px] text-foreground outline-none focus:border-[var(--adp-accent)]"
          />
        </label>
        {error ? <p className="mt-2 text-[13px] text-red-500">{error}</p> : null}
        <div className="mt-5 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md border border-border px-3.5 py-1.5 text-[13px] font-medium text-muted-foreground transition hover:text-foreground disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={!armed}
            className="rounded-md bg-red-600 px-3.5 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
          >
            {busy ? "Deleting…" : "Delete everything"}
          </button>
        </div>
      </div>
    </div>
  );
}
