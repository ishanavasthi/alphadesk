"use client";

import { useEffect } from "react";
import { useUser } from "@clerk/nextjs";

/**
 * Reports the signed-in reader's first name to the portfolio greeting.
 *
 * Lives under `components/clerk/` (the only place `@clerk/nextjs` may be
 * imported — see `tests/auth-boundaries.test.ts`) and is reached exclusively
 * through a flag-gated `next/dynamic` import in `Greeting`, so a flag-off
 * build never fetches the Clerk chunk. Renders nothing itself; the greeting
 * reads perfectly well with no name, which is also the single-tenant and
 * signed-out state.
 */
export function ClerkFirstName({ onName }: { onName: (name: string | null) => void }) {
  const { isLoaded, isSignedIn, user } = useUser();
  useEffect(() => {
    if (!isLoaded) return;
    onName(isSignedIn ? (user?.firstName ?? null) : null);
  }, [isLoaded, isSignedIn, user, onName]);
  return null;
}
