import type { ReactNode } from "react";

import { ClerkIdentityProvider } from "@/components/clerk/ClerkIdentityProvider";
import { AUTH_ENABLED } from "@/lib/auth";

/**
 * Platform identity (Clerk), mounted only when `NEXT_PUBLIC_AUTH_ENABLED=true`.
 *
 * **Deliberately not a client component.** A client chunk that a server
 * component never renders is never sent to the browser, so with the flag off a
 * visitor downloads not one byte of Clerk — the guarantee card F2 is built
 * around. Adding `"use client"` here would ship Clerk to everyone and merely
 * decline to run it. (`components/UserMenu.tsx` cannot use this trick — it sits
 * under a client component already — which is why that one reaches for
 * `next/dynamic` instead.)
 *
 * Rendered from `app/layout.tsx` *inside* `<body>`: Clerk Core 3 requires
 * `<ClerkProvider>` there rather than wrapping `<html>`.
 */
export function Identity({ children }: { children: ReactNode }) {
  if (!AUTH_ENABLED) return <>{children}</>;
  return <ClerkIdentityProvider>{children}</ClerkIdentityProvider>;
}
