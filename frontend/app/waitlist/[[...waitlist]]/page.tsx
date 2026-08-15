import { notFound } from "next/navigation";

import { ClerkWaitlist } from "@/components/clerk/ClerkAuthPages";
import { AUTH_ENABLED } from "@/lib/auth";

/**
 * `/waitlist` — Clerk's prebuilt waitlist form.
 *
 * AlphaDesk opens in **Waitlist mode**: joining is a request, not a signup.
 * Someone who submits this form gets a confirmation email, and a second email
 * with sign-in instructions once an operator approves them in the Clerk
 * Dashboard. Approval is a human act; nothing in this repo grants it.
 *
 * Waitlist mode itself is a **Clerk Dashboard setting** (Configure -> Restrictions
 * -> Sign-up mode -> Waitlist), not a prop. Rendering this component against an
 * instance that is not in Waitlist mode gets an error from Clerk, not a form —
 * see `docs/TESTING/F2.md` §4.
 *
 * Same flag semantics as `/sign-in`: off means 404, exactly as before card F2.
 */
export default function WaitlistPage() {
  if (!AUTH_ENABLED) notFound();
  return (
    <main className="flex min-h-[calc(100vh-3rem)] items-center justify-center px-4 py-16">
      <ClerkWaitlist />
    </main>
  );
}
