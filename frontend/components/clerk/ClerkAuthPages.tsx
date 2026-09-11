"use client";

import { SignIn, SignUp } from "@clerk/nextjs";

/**
 * The two full-page Clerk forms, kept behind this module's client boundary.
 *
 * They are trivial wrappers and exist only so that `app/sign-in/...` and
 * `app/sign-up/...` can stay **server** components — which is what lets them
 * call `notFound()` when the flag is off, and what keeps `@clerk/nextjs` out of
 * a build that will never render either form.
 *
 * `ClerkWaitlist` lived here until general availability. Clerk's `<Waitlist />`
 * renders an error rather than a form against an instance that is not in
 * Waitlist mode, so an open-sign-up instance has no use for it.
 */

export function ClerkSignIn() {
  return <SignIn />;
}

export function ClerkSignUp() {
  return <SignUp />;
}
