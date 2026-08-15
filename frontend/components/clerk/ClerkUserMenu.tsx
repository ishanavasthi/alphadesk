"use client";

import { SignInButton, UserButton, useUser } from "@clerk/nextjs";

/**
 * The top-bar identity control: avatar menu when signed in, "Sign in" when not.
 *
 * Rendered only from `TopBar`'s `AUTH_ENABLED` branch — see
 * `ClerkIdentityProvider` for why that branch living in a *server* component is
 * what keeps Clerk out of the flag-off bundle.
 *
 * `useUser().isLoaded` rather than Core 3's `<Show>`: this control sits in a
 * fixed-height row next to the IND Money button, and a control that pops into
 * existence after hydration shifts that row. Reserving the space while Clerk
 * loads costs one `div` and avoids the jump.
 */
export function ClerkUserMenu() {
  const { isLoaded, isSignedIn } = useUser();

  if (!isLoaded) {
    // Same footprint as the avatar it becomes, so the row never reflows.
    return <div className="h-7 w-7" aria-hidden />;
  }

  if (!isSignedIn) {
    return (
      <SignInButton mode="redirect">
        <button
          type="button"
          className="eyebrow text-muted-foreground transition-colors hover:text-foreground"
        >
          Sign in
        </button>
      </SignInButton>
    );
  }

  return <UserButton appearance={{ elements: { avatarBox: "h-7 w-7" } }} />;
}
