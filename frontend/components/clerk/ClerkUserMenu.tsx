"use client";

import { SignInButton, UserButton, useUser } from "@clerk/nextjs";
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { DeleteMyDataDialog } from "@/components/clerk/DeleteMyDataDialog";

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
  const [deleteOpen, setDeleteOpen] = useState(false);

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

  return (
    <>
      <UserButton appearance={{ elements: { avatarBox: "h-7 w-7" } }}>
        {/* The DPDP "delete my data" action lives in the account menu (a4-shell).
            It opens an explicit type-to-confirm dialog before anything happens. */}
        <UserButton.MenuItems>
          <UserButton.Action
            label="Delete my data"
            labelIcon={<Trash2 className="h-3.5 w-3.5" />}
            onClick={() => setDeleteOpen(true)}
          />
        </UserButton.MenuItems>
      </UserButton>
      <DeleteMyDataDialog open={deleteOpen} onClose={() => setDeleteOpen(false)} />
    </>
  );
}
