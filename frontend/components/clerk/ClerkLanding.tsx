"use client";

import { useUser } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { useIndMoney } from "@/components/AuthProvider";
import { useLinkConsent } from "@/components/consent/LinkConsent";
import { ConnectGate } from "@/components/portfolio/states";
import { startAuthLogin } from "@/lib/api";

/**
 * The landing route's auth-aware branch (card U1), rendered only with the flag
 * on — see `app/(marketing)/page.tsx`, which renders the plain marketing hero
 * directly when `NEXT_PUBLIC_AUTH_ENABLED` is off so a flag-off build downloads
 * no Clerk (the F2 containment guarantee: `@clerk/nextjs` is imported only from
 * `components/clerk/`).
 *
 * The three signed-in-plus-link states from the plan's route table:
 *
 * | State | `/` renders |
 * | --- | --- |
 * | signed out | the marketing hero (`children`) |
 * | signed in + IND Money linked | redirect → `/portfolio` |
 * | signed in, not linked | the Connect gate |
 *
 * "Signed in" is Clerk (`useUser`); "linked" is a per-user IND Money fact
 * (`useIndMoney`, F3). The two are genuinely independent, so both are consulted.
 * While either is still resolving the hero stays on screen — never a flash of
 * the gate at someone who is actually linked.
 */
export function ClerkLanding({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn } = useUser();
  const { authed } = useIndMoney();
  const router = useRouter();

  const linked = isSignedIn === true && authed === true;

  useEffect(() => {
    if (linked) router.replace("/portfolio");
  }, [linked, router]);

  // Clerk still hydrating, or signed out: the public landing is the right answer.
  if (!isLoaded || !isSignedIn) return <>{children}</>;

  // Signed in, link state not yet known.
  if (authed === null) {
    return <Centered>Checking your account…</Centered>;
  }

  // Signed in and linked: the effect above is navigating to the dashboard.
  if (authed) {
    return <Centered>Opening your portfolio…</Centered>;
  }

  // Signed in, not linked: the Connect gate.
  return <ConnectGateBranch />;
}

function ConnectGateBranch() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { begin: beginConsent, dialog: consentDialog } = useLinkConsent();

  const runConnect = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const url = await startAuthLogin();
      window.location.href = url;
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }, []);

  // Consent-at-link-time (card L1): the gate button opens the consent screen,
  // and only agreeing there starts OAuth.
  const connect = useCallback(() => beginConsent(runConnect), [beginConsent, runConnect]);

  return (
    <div className="mx-auto max-w-[1120px] px-4 sm:px-6">
      <ConnectGate onConnect={connect} busy={busy} error={error} />
      {consentDialog}
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="pt-24 text-center text-[13px] text-muted-foreground">{children}</div>
  );
}
