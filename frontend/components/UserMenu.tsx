"use client";

import dynamic from "next/dynamic";

import { AUTH_ENABLED } from "@/lib/auth";

/**
 * The top bar's "who are you" slot — Clerk when the flag is on, nothing when off.
 *
 * ## Why `next/dynamic` and not a plain import behind an `if`
 *
 * This slot is a **client** component (it uses `next/dynamic`), so a static
 * `import { ClerkUserMenu }` here would be linked into the page's
 * **initial** bundle and shipped to every visitor, flag or no flag — whether the
 * minifier then eliminated it would come down to how well cross-module constant
 * folding happened to work that release.
 *
 * `dynamic(() => import(...))` removes the question. An async import is a
 * separate chunk by construction; with the flag off `dynamic()` is never called,
 * so the chunk is never requested. The server-side gate in `app/layout.tsx` gets
 * the same guarantee for free, because that file is a server component — this
 * one cannot be.
 */
const ClerkUserMenu = AUTH_ENABLED
  ? dynamic(() => import("@/components/clerk/ClerkUserMenu").then((m) => m.ClerkUserMenu))
  : null;

export function UserMenu() {
  return ClerkUserMenu ? <ClerkUserMenu /> : null;
}
