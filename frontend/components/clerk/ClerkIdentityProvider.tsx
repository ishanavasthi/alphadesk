"use client";

import { ClerkProvider, useAuth } from "@clerk/nextjs";
import { useEffect, type ReactNode } from "react";

import { setSessionTokenGetter } from "@/lib/auth";

/**
 * `<ClerkProvider>` plus the bridge that lets `lib/api.ts` mint session tokens.
 *
 * **Every module under `components/clerk/` imports `@clerk/nextjs`, and nothing
 * outside this directory does.** That is the whole containment strategy: these
 * components are rendered only from a *server* component's `AUTH_ENABLED`
 * branch, and a client chunk a server component never renders is never sent to
 * the browser. With the flag off the visitor downloads exactly the JavaScript
 * they downloaded before card F2.
 *
 * Placement note (Clerk Core 3 breaking change): `<ClerkProvider>` must live
 * **inside `<body>`**, not wrapping `<html>`. `app/layout.tsx` does that.
 */

/**
 * Hands Clerk's `getToken` to the plain-module API client. Renders nothing.
 *
 * Cleanup on unmount clears the getter, so a torn-down tree cannot leave
 * `lib/api.ts` holding a closure over a dead Clerk instance.
 */
function SessionTokenBridge() {
  const { getToken } = useAuth();

  useEffect(() => {
    setSessionTokenGetter(() => getToken());
    return () => setSessionTokenGetter(null);
  }, [getToken]);

  return null;
}

export function ClerkIdentityProvider({ children }: { children: ReactNode }) {
  return (
    <ClerkProvider
      // Sign-up is open, so the "no account?" link on the sign-in card points
      // at the real sign-up form. Clerk needs the URL to build that link; with
      // neither `signUpUrl` nor `waitlistUrl` set it renders no link at all and
      // a new visitor reaches the sign-in card with no way forward.
      signUpUrl="/sign-up"
      signInUrl="/sign-in"
      signInFallbackRedirectUrl="/"
      signUpFallbackRedirectUrl="/"
      afterSignOutUrl="/"
    >
      <SessionTokenBridge />
      {children}
    </ClerkProvider>
  );
}
