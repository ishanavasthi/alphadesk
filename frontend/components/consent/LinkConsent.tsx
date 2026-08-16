"use client";

import { useCallback, useRef, useState, type ReactNode } from "react";

/**
 * Consent-at-link-time (card L1).
 *
 * Before AlphaDesk sends anyone to IND Money's OAuth screen, it shows exactly
 * what the link will and will not do. This is a **required step in the link
 * flow**, not a checkbox buried in sign-up: every Connect button routes its OAuth
 * start through {@link useLinkConsent}, so there is no path to `/auth/login` that
 * skips it.
 *
 * The copy is single-sourced here so the three Connect entry points (the Lab
 * top-bar button, the `/portfolio` gate, and the landing gate) cannot drift.
 */

/** What linking IND Money grants AlphaDesk read access to. */
export const CONSENT_READS: readonly string[] = [
  "Your holdings — stocks, mutual funds, and other assets",
  "Their current values and, where the source has it, what you invested",
  "Your SIPs (systematic investment plans)",
  "Your net-worth totals and allocation breakdowns",
];

/** What linking never does — the reassurances that matter most. */
export const CONSENT_NEVER: readonly string[] = [
  "No trading. AlphaDesk can never place, change, or cancel an order — it is read-only.",
  "No credentials. You sign in on IND Money's own page over OAuth; AlphaDesk never sees your password.",
  "No advice. Everything shown is descriptive analytics, not a recommendation.",
];

/**
 * Drive an OAuth start through a consent screen.
 *
 * `begin(proceed)` opens the dialog; `proceed` runs only if the user agrees, and
 * it runs **synchronously inside the agree click** so a call site that opens a
 * popup keeps its user-activation. `dialog` is the node the call site renders.
 */
export function useLinkConsent(): {
  begin: (proceed: () => void | Promise<void>) => void;
  dialog: ReactNode;
} {
  const [open, setOpen] = useState(false);
  const proceedRef = useRef<null | (() => void | Promise<void>)>(null);

  const begin = useCallback((proceed: () => void | Promise<void>) => {
    proceedRef.current = proceed;
    setOpen(true);
  }, []);

  const agree = useCallback(() => {
    const proceed = proceedRef.current;
    proceedRef.current = null;
    setOpen(false);
    // Run inside the click so a synchronous window.open keeps its activation.
    void proceed?.();
  }, []);

  const cancel = useCallback(() => {
    proceedRef.current = null;
    setOpen(false);
  }, []);

  return {
    begin,
    dialog: <LinkConsentDialog open={open} onAgree={agree} onCancel={cancel} />,
  };
}

function LinkConsentDialog({
  open,
  onAgree,
  onCancel,
}: {
  open: boolean;
  onAgree: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div
      role="presentation"
      onClick={onCancel}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
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
        aria-labelledby="link-consent-title"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-lg border border-border bg-background p-5 text-foreground shadow-xl"
      >
        <h2 id="link-consent-title" className="text-base font-semibold tracking-[-0.01em]">
          Before you connect IND Money
        </h2>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
          Connecting gives AlphaDesk <b className="font-semibold text-foreground">read-only</b>{" "}
          access, over IND Money&rsquo;s OAuth, to:
        </p>
        <ul className="mt-2.5 space-y-1.5 text-[13px]">
          {CONSENT_READS.map((item) => (
            <li key={item} className="flex gap-2">
              <span aria-hidden className="text-[var(--adp-accent)]">
                ✓
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3.5 text-[13px] font-medium text-foreground">What it never does:</p>
        <ul className="mt-1.5 space-y-1.5 text-[13px] text-muted-foreground">
          {CONSENT_NEVER.map((item) => (
            <li key={item} className="flex gap-2">
              <span aria-hidden>·</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3.5 text-xs text-[var(--adp-faint)]">
          You can disconnect and{" "}
          <a className="underline hover:text-foreground" href="/privacy">
            delete your data
          </a>{" "}
          at any time. See the{" "}
          <a className="underline hover:text-foreground" href="/privacy">
            privacy policy
          </a>
          .
        </p>
        <div className="mt-5 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border px-3.5 py-1.5 text-[13px] font-medium text-muted-foreground transition hover:text-foreground"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onAgree}
            className="rounded-md bg-[var(--adp-accent)] px-3.5 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110"
          >
            Agree &amp; connect
          </button>
        </div>
      </div>
    </div>
  );
}
