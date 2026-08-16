import type { Metadata } from "next";

import { AUTH_ENABLED } from "@/lib/auth";
import { AuthProvider } from "@/components/AuthProvider";
import { LandingHero } from "@/components/shell/LandingHero";
import { ClerkLanding } from "@/components/clerk/ClerkLanding";

export const metadata: Metadata = {
  title: "AlphaDesk — your whole portfolio, one honest dashboard",
  description:
    "Link your IND Money account and see net worth, allocation and history — computed, verified, and narrated. Not investment advice.",
};

/**
 * `/` — the public landing (plan route table).
 *
 * | Visitor | Renders |
 * | --- | --- |
 * | anonymous (or flag off) | the marketing hero |
 * | signed in + IND Money linked | redirect → `/portfolio` |
 * | signed in, not linked | the Connect gate |
 *
 * With `NEXT_PUBLIC_AUTH_ENABLED` off there is no "signed in" state at all, so
 * this returns the plain hero and — because a server component that never
 * renders `ClerkLanding` never sends its client chunk — ships no Clerk. Flag on,
 * `ClerkLanding` (a `components/clerk/` module, per F2 containment) resolves the
 * signed-in branches on the client, falling back to this same hero when signed
 * out.
 */
export default function Home() {
  const hero = <LandingHero authEnabled={AUTH_ENABLED} />;
  if (!AUTH_ENABLED) return hero;
  // AuthProvider is mounted here, not globally, so it pings the IND Money link
  // only on the surface that routes on it — never on `/demo` or a static page.
  return (
    <AuthProvider>
      <ClerkLanding>{hero}</ClerkLanding>
    </AuthProvider>
  );
}
