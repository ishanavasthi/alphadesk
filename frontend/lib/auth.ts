/**
 * The auth feature flag, and the one place the app can ask for a Clerk token.
 *
 * Card F2 lands Clerk with the whole thing switched off. `NEXT_PUBLIC_AUTH_ENABLED`
 * is the switch, and it is read here and only here so that "is sign-in on?" has
 * exactly one answer everywhere in the bundle.
 *
 * **The flag is a build-time constant, not a runtime setting.** Next inlines
 * every `NEXT_PUBLIC_*` value into the JavaScript at build time, so flipping it
 * means a rebuild and redeploy — which is the intent: L1 is a deliberate
 * release, not a dashboard toggle.
 *
 * ## Why a token *getter* rather than a token
 *
 * Clerk session tokens are short-lived (about a minute) and Clerk refreshes them
 * in the background. Caching one here would mean serving a stale token minutes
 * later; `getToken()` hands back a fresh one on every call. So the React tree
 * registers Clerk's `getToken` here once (see `ClerkIdentityProvider`), and
 * `lib/api.ts` — which is a plain module with no hooks available — asks for it
 * per request.
 *
 * With the flag off nothing ever registers a getter, `sessionToken()` returns
 * `null` without touching Clerk, and `withAuth()` returns the caller's headers
 * unchanged. That is what keeps every request byte-identical to today.
 */

/** Is Clerk sign-in compiled into this build? Inlined by Next at build time. */
export const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

/** Resolves to a fresh Clerk session token, or `null` when signed out. */
export type SessionTokenGetter = () => Promise<string | null>;

let getter: SessionTokenGetter | null = null;

/**
 * Register (or clear, with `null`) the function that mints session tokens.
 *
 * Called from inside `<ClerkProvider>`, which is the only place Clerk's
 * `getToken` exists. Exported for tests too — a test can register a stub and
 * assert on the header without a Clerk instance.
 */
export function setSessionTokenGetter(next: SessionTokenGetter | null): void {
  getter = next;
}

/**
 * The current Clerk session token, or `null`.
 *
 * Never throws. A failure to mint a token means "this request goes out
 * unauthenticated and the backend decides" — not "the UI explodes". Clerk Core
 * 3's `getToken` throws `clerk_runtime_not_browser` when called outside the
 * browser, which is a normal thing to hit during SSR and must not surface.
 */
export async function sessionToken(): Promise<string | null> {
  if (!AUTH_ENABLED || !getter) return null;
  try {
    return await getter();
  } catch {
    return null;
  }
}

/**
 * `init.headers` plus `Authorization: Bearer <token>` when there is a session.
 *
 * Returns the input untouched when the flag is off or nobody is signed in, so a
 * caller cannot tell the difference between this build and the pre-F2 one.
 */
export async function withAuth(headers?: HeadersInit): Promise<HeadersInit | undefined> {
  const token = await sessionToken();
  if (!token) return headers;
  const merged = new Headers(headers);
  merged.set("Authorization", `Bearer ${token}`);
  return merged;
}
