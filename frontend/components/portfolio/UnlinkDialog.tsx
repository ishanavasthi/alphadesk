"use client";

import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { unlinkIndMoney } from "@/lib/api";

/**
 * "Disconnect IND Money" (issue #13).
 *
 * Deliberately lighter ceremony than "Delete my data": nothing is destroyed and
 * re-linking is one Connect press away, so it asks once and takes the answer —
 * no type-to-confirm.
 *
 * The one state worth a second beat is a **failed upstream revocation**. The
 * backend unlinks locally either way (refusing would strand the user), but
 * "we forgot your token" is not "your access is gone" — so when the grant
 * survives at the source the dialog says so instead of closing on a claim that
 * is not true. `onUnlinked` fires when the dialog is done rather than the moment
 * the call returns: a refresh flips the whole surface to the Connect gate, which
 * would take this dialog — and that caveat — down with it.
 */
export function UnlinkDialog({
  open,
  onOpenChange,
  onUnlinked,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUnlinked: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Unlinked here, but the grant is still live at IND Money's end. */
  const [caveat, setCaveat] = useState(false);

  const close = () => {
    setError(null);
    setCaveat(false);
    onOpenChange(false);
  };

  const finish = () => {
    close();
    onUnlinked();
  };

  const onUnlink = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await unlinkIndMoney();
      setBusy(false);
      // Nothing was revoked because there was nothing to revoke: an already
      // unlinked account is a done deal, not a caveat.
      if (result.upstream_revoked || result.status === "not_linked") finish();
      else setCaveat(true);
    } catch (err) {
      setError((err as Error).message || "Disconnect failed. Please try again.");
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {caveat ? "Disconnected here" : "Disconnect IND Money?"}
          </DialogTitle>
          <DialogDescription>
            {caveat
              ? "AlphaDesk no longer has access to your IND Money account, but the source did not confirm the revocation — the app's access may still be listed on IND Money's side and worth removing from your account there."
              : "AlphaDesk stops reading your holdings and deletes the stored connection. Your saved snapshots and watchlist stay. You can reconnect any time."}
          </DialogDescription>
        </DialogHeader>
        {error ? <p className="text-[13px] text-red-500">{error}</p> : null}
        <DialogFooter>
          {caveat ? (
            <button
              type="button"
              onClick={finish}
              className="rounded-md border border-border px-3.5 py-1.5 text-[13px] font-medium text-foreground transition hover:bg-muted"
            >
              Done
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={close}
                disabled={busy}
                className="rounded-md border border-border px-3.5 py-1.5 text-[13px] font-medium text-muted-foreground transition hover:text-foreground disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void onUnlink()}
                disabled={busy}
                className="rounded-md bg-red-600 px-3.5 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
              >
                {busy ? "Disconnecting…" : "Unlink"}
              </button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
