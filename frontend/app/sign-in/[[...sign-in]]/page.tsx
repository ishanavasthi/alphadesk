import { notFound } from "next/navigation";

import { ClerkSignIn } from "@/components/clerk/ClerkAuthPages";
import { AUTH_ENABLED } from "@/lib/auth";

/**
 * `/sign-in` — Clerk's prebuilt sign-in card.
 *
 * Optional catch-all (`[[...sign-in]]`) because Clerk routes its own multi-step
 * flows — factor two, password reset, SSO callback — as sub-paths of this one.
 * A plain `page.tsx` here would 404 halfway through a sign-in.
 *
 * **Flag off, this route does not exist.** `notFound()` rather than a redirect
 * or an empty page: before card F2 a visitor to `/sign-in` got a 404, and they
 * should still. A server component owns that decision so the Clerk chunk is
 * never sent to a visitor who cannot use it.
 *
 * In Waitlist mode this page is reachable, but only an approved account can get
 * through it; everyone else is pointed at `/waitlist` by the card's own link
 * (that link exists because `<ClerkProvider waitlistUrl>` is set).
 */
export default function SignInPage() {
  if (!AUTH_ENABLED) notFound();
  return (
    <main className="flex min-h-[calc(100vh-3rem)] items-center justify-center px-4 py-16">
      <ClerkSignIn />
    </main>
  );
}
