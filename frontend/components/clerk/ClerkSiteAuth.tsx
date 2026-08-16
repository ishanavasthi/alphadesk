"use client";

import Link from "next/link";
import { SignInButton, UserButton, useUser } from "@clerk/nextjs";

/**
 * The shadcn site header's identity control — signed-in avatar + a Portfolio
 * link, or "Sign in" / "Join waitlist" when signed out.
 *
 * Rendered only from `SiteAuthSlot`'s `AUTH_ENABLED` branch (a `next/dynamic`
 * gate), so with the flag off this module — and `@clerk/nextjs` with it — is
 * never sent to the browser. Same containment as `ClerkUserMenu`; this is the
 * light-surface counterpart for `/` and the other product pages.
 *
 * `useUser().isLoaded` reserves the control's width while Clerk hydrates so the
 * header does not reflow.
 */
export function ClerkSiteAuth() {
  const { isLoaded, isSignedIn } = useUser();

  if (!isLoaded) return <div className="h-7 w-16" aria-hidden />;

  if (!isSignedIn) {
    return (
      <div className="flex items-center gap-3 text-[13px]">
        <SignInButton mode="redirect">
          <button
            type="button"
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            Sign in
          </button>
        </SignInButton>
        <Link
          href="/waitlist"
          className="rounded-md bg-[var(--adp-accent)] px-3 py-1.5 text-white transition-colors hover:bg-[#1d4ed8]"
        >
          Join waitlist
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 text-[13px]">
      <Link
        href="/portfolio"
        className="text-muted-foreground transition-colors hover:text-foreground"
      >
        Portfolio
      </Link>
      <UserButton appearance={{ elements: { avatarBox: "h-7 w-7" } }} />
    </div>
  );
}
