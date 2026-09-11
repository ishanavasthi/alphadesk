import { notFound } from "next/navigation";

import { ClerkSignUp } from "@/components/clerk/ClerkAuthPages";
import { AUTH_ENABLED } from "@/lib/auth";

/**
 * `/sign-up` — Clerk's prebuilt sign-up card.
 *
 * Optional catch-all (`[[...sign-up]]`) for the same reason as `/sign-in`:
 * Clerk routes its own multi-step flows — email verification, SSO callback —
 * as sub-paths of this one, and a plain `page.tsx` would 404 halfway through.
 *
 * **Flag off, this route does not exist**, exactly as `/sign-in` behaves. A
 * server component owns that decision so the Clerk chunk is never sent to a
 * visitor who cannot use it.
 *
 * This route replaced `/waitlist` at general-availability: sign-up is open, so
 * creating an account is a self-serve act rather than a request an operator
 * approves. `/waitlist` permanently redirects here (see `next.config.mjs`) so
 * the links in already-sent Clerk waitlist emails still land somewhere useful.
 */
export default function SignUpPage() {
  if (!AUTH_ENABLED) notFound();
  return (
    <main className="flex min-h-[calc(100vh-3rem)] items-center justify-center px-4 py-16">
      <ClerkSignUp />
    </main>
  );
}
