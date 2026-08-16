"use client";

import dynamic from "next/dynamic";

import { AUTH_ENABLED } from "@/lib/auth";

/**
 * The site header's identity slot — Clerk when the flag is on, nothing when off.
 *
 * Same `next/dynamic` gate as `components/UserMenu.tsx`: the header is a client
 * subtree, so a plain import of the Clerk control would be linked into the
 * initial bundle and shipped to every visitor. An async import is a separate
 * chunk by construction, and with the flag off `dynamic()` is never called, so
 * the chunk — and `@clerk/nextjs` — is never requested.
 */
const ClerkSiteAuth = AUTH_ENABLED
  ? dynamic(() => import("@/components/clerk/ClerkSiteAuth").then((m) => m.ClerkSiteAuth))
  : null;

export function SiteAuthSlot() {
  return ClerkSiteAuth ? <ClerkSiteAuth /> : null;
}
