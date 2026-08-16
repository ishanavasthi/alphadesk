"use client";

import type { ReactNode } from "react";
import { Badge, Button, Card, EmptyCallout } from "./ui";

/**
 * Full-page states for `/portfolio`, per `a4-shell.html`.
 *
 * The rule they all share: a state the product *expects* is never rendered as an
 * error. An unlinked account is a next step, not a failure; a throttled source
 * is a wait, not an outage; a boundary we have not verified is a withheld answer,
 * not an empty portfolio.
 */
function Gate({
  glyph,
  title,
  children,
}: {
  glyph: string;
  title: string;
  children: ReactNode;
}) {
  // Padding, not a top margin: a margin here collapses through the route
  // wrapper and lets the terminal page's near-black body show above the card.
  return (
    <div className="mx-auto max-w-lg pt-16">
      <Card className="px-5 py-7 text-center">
        <div className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-[10px] bg-[var(--adp-accent-soft)] text-xl text-[var(--adp-accent)]">
          {glyph}
        </div>
        <h2 className="mb-1.5 text-[17px] font-semibold">{title}</h2>
        {children}
      </Card>
    </div>
  );
}

/**
 * Unlinked (the API answered 409).
 *
 * The consent list is not decoration: it is the last screen before the user is
 * redirected to authorize, so it states exactly what will be read and — just as
 * explicitly — what cannot happen. "Never order placement" is true at the code
 * level; the broker layer is a stub.
 *
 * Every claim here has to be true *today*, not once some later card lands. The
 * token line therefore says "stored server-side" and stops: the OAuth token
 * currently sits in plaintext in `backend/.ind_money_token.json`, and card F3 is
 * what moves it into the Fernet-encrypted `broker_links` column. Promising
 * encryption a card early would be the one lie on the consent screen.
 */
export function ConnectGate({
  onConnect,
  busy,
  error,
}: {
  onConnect: () => void;
  busy: boolean;
  error: string | null;
}) {
  return (
    <Gate glyph="⛓" title="Link your IND Money account">
      <p className="mb-3.5 text-[13px] text-muted-foreground">
        Read-only access, revocable any time. Before you&rsquo;re redirected, here is exactly what
        AlphaDesk will read:
      </p>
      <ul className="mx-auto mb-4 max-w-[330px] text-left text-[12.5px] text-muted-foreground">
        {[
          ["yes", "Portfolio holdings, values and SIPs"],
          ["yes", "Net-worth totals for daily snapshots"],
          ["no", "Never order placement — the broker layer cannot trade"],
          ["no", "Never your credentials — OAuth only, tokens stored server-side"],
        ].map(([kind, text]) => (
          <li key={text} className="flex gap-2 py-1">
            <span
              className={kind === "yes" ? "font-bold text-[var(--adp-good)]" : "font-bold text-[var(--adp-bad)]"}
              aria-hidden
            >
              {kind === "yes" ? "✓" : "✕"}
            </span>
            <span>{text}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <Button variant="accent" onClick={onConnect} disabled={busy}>
          {busy ? "Opening IND Money…" : "Continue to IND Money →"}
        </Button>
      </div>
      {error ? <p className="mt-3 text-xs text-[var(--adp-bad)]">{error}</p> : null}
    </Gate>
  );
}

/**
 * This build has no credential it could send.
 *
 * The backend is per-user as of card F3, so the credential that matters is a
 * Clerk session token. This state renders only in a build compiled with
 * `NEXT_PUBLIC_AUTH_ENABLED` off — with the flag on (the shipped state after
 * L1) a signed-out visitor sees the sign-in prompt instead.
 */
export function LockedState() {
  return (
    <Gate glyph="🔒" title="Portfolio is locked on this deployment">
      <p className="mb-3 text-[13px] text-muted-foreground">
        The backend serves each person their own portfolio, but sign-in is not switched on in
        this build — so there is no account to see it as.
      </p>
      <p className="text-xs text-[var(--adp-faint)]">
        This is a build compiled with sign-in disabled. The live site has it on;
        sign in there to see your own dashboard.
      </p>
    </Gate>
  );
}

/** The backend answered 401: no valid session. */
export function UnauthorizedState() {
  return (
    <Gate glyph="⚠" title="Not signed in">
      <p className="text-[13px] text-muted-foreground">
        The backend answered 401. Sign in to see your own portfolio.
      </p>
    </Gate>
  );
}

/** Any source failure that is not one of the states above. */
export function SourceErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Gate glyph="⚠" title="The portfolio source could not be read">
      <p className="mb-3.5 text-[13px] text-muted-foreground">{message}</p>
      <Button variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </Gate>
  );
}

/**
 * Rate limited — quiet and inline, never an error screen.
 *
 * The source allows 15 calls/min per tool and 30/min overall. Being throttled is
 * an ordinary consequence of asking, so it reads as a wait with the source's own
 * suggested delay, and the numbers already on screen stay on screen.
 */
export function RateLimitedNotice({ retryAfter }: { retryAfter: number | null }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--adp-warn-ink)]" aria-hidden />
      The source is rate-limiting; retrying
      {retryAfter ? ` in ~${Math.ceil(retryAfter)}s` : " shortly"}.
    </div>
  );
}

/**
 * The IND_STOCK boundary (M1 §7).
 *
 * No populated Indian-stock row has ever been observed from this source, so the
 * connector refuses to guess at one. Rendering an empty table here would state
 * "you hold no Indian stocks" — the single most misleading thing this dashboard
 * could say, on the one asset class it exists for.
 */
export function UnverifiedShapeNotice({ label }: { label: string }) {
  return (
    <EmptyCallout icon="⚠" className="mt-3.5">
      <b className="font-semibold text-foreground">{label} rows can&rsquo;t be shown yet</b> —
      unverified source shape. The source returned a row layout this integration has never seen
      populated, so those rows are withheld rather than guessed at. Totals above still include
      them.
    </EmptyCallout>
  );
}

/** A bucket the snapshot reports but the source cannot enumerate (the EPF case). */
export function SourceEmptyNotice({ label, value }: { label: string; value: string }) {
  return (
    <EmptyCallout className="mt-3.5">
      <b className="font-semibold text-foreground">{label}</b> appears in your snapshot ({value})
      but the source returns no holding-level rows for it — the totals include it, the table
      can&rsquo;t.
    </EmptyCallout>
  );
}
