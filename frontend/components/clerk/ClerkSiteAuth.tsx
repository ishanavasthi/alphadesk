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

  if (!isLoaded) return <div className="h-7 w-16 flex-none" aria-hidden />;

  // `flex-none` + `whitespace-nowrap` throughout: this control is the last item
  // in the header's flex row, and without them a narrow phone row shrinks it
  // until "Sign in" wraps mid-label and "Join waitlist" is clipped off the right
  // edge. It is the row's fixed anchor; the spacer beside it absorbs the slack.
  if (!isSignedIn) {
    return (
      <div className="flex flex-none items-center gap-2.5 whitespace-nowrap text-[13px] sm:gap-3">
        <SignInButton mode="redirect">
          <button
            type="button"
            className="whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground"
          >
            Sign in
          </button>
        </SignInButton>
        <Link
          href="/waitlist"
          className="whitespace-nowrap rounded-md bg-[var(--adp-accent)] px-2.5 py-1.5 text-white transition-colors hover:bg-[#1d4ed8] sm:px-3"
        >
          Join waitlist
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-none items-center gap-2.5 whitespace-nowrap text-[13px] sm:gap-3">
      <Link
        href="/portfolio"
        className="whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground"
      >
        Portfolio
      </Link>
      <UserButton appearance={{ elements: { avatarBox: "h-7 w-7" } }} />
    </div>
  );
}
