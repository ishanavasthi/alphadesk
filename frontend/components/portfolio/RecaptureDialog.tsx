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
import type { CapturedReading } from "@/lib/api";
import { Button } from "@/components/ui/adp";
import { inr, num } from "./format";

const IST_TIME = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/**
 * "Replace today's snapshot?" — offered when Capture finds the day already taken.
 *
 * The first reading of a day is not necessarily its true one: IND Money serves
 * a stale bank balance until the user refreshes it in their app, and the
 * nightly job (or simply opening this page) may have locked the day before
 * that. AlphaDesk cannot trigger that refresh, so the dialog says so, and shows
 * the stored reading so the reader knows what they are replacing.
 *
 * Nothing is lost on a failure: the backend reads the source first and keeps
 * the earlier reading if that read fails or comes back partial, and this dialog
 * stays open with the reason.
 */
export function RecaptureDialog({
  offer,
  onDismiss,
  onRecapture,
}: {
  offer: CapturedReading | null;
  onDismiss: () => void;
  onRecapture: () => Promise<string | null>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    if (busy) return;
    setError(null);
    onDismiss();
  };

  const replace = async () => {
    setBusy(true);
    setError(null);
    const reason = await onRecapture();
    setBusy(false);
    if (reason) setError(reason);
  };

  const total = offer ? num(offer.total_value) : null;
  const at = offer?.captured_at ? IST_TIME.format(new Date(offer.captured_at)) : null;

  return (
    <Dialog open={offer !== null} onOpenChange={(next) => (next ? undefined : close())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Replace today&rsquo;s snapshot?</DialogTitle>
          <DialogDescription>
            Today already has a snapshot
            {total !== null ? (
              <>
                {" "}
                of <span className="adp-num font-medium text-foreground">{inr(total)}</span>
              </>
            ) : null}
            {at ? <> taken at {at} IST</> : null}. Replacing it reads IND Money again now and
            stores that reading for today instead.
          </DialogDescription>
        </DialogHeader>
        <p className="m-0 text-[13px] text-muted-foreground">
          If a bank balance looked stale, refresh it in the IND Money app first — AlphaDesk can
          only read what IND Money currently reports.
        </p>
        {error ? (
          <p className="m-0 text-[13px] text-[var(--adp-bad)]" role="alert">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={close} disabled={busy}>
            Keep current
          </Button>
          <Button variant="primary" size="sm" onClick={() => void replace()} disabled={busy}>
            {busy ? "Reading IND Money…" : "Replace with a fresh reading"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
