"use client";

import { SignIn, Waitlist } from "@clerk/nextjs";

/**
 * The two full-page Clerk forms, kept behind this module's client boundary.
 *
 * They are trivial wrappers and exist only so that `app/sign-in/...` and
 * `app/waitlist/...` can stay **server** components — which is what lets them
 * call `notFound()` when the flag is off, and what keeps `@clerk/nextjs` out of
 * a build that will never render either form.
 */

export function ClerkSignIn() {
  return <SignIn />;
}

export function ClerkWaitlist() {
  return <Waitlist />;
}
