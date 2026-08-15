import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

/**
 * Clerk's middleware — active only when `NEXT_PUBLIC_AUTH_ENABLED=true`.
 *
 * `<ClerkProvider>` cannot read auth state during a server render unless
 * `clerkMiddleware()` has run on the request first, so this file is not
 * optional once the flag is on.
 *
 * ## Flag off
 *
 * The exported handler is a bare `NextResponse.next()`: it adds no header,
 * rewrites nothing, redirects nothing, and — importantly — never constructs
 * `clerkMiddleware()`, which throws without a publishable key. A response
 * served with the flag off is identical to one served before card F2.
 *
 * The one honest caveat is that this file's *existence* means Next registers a
 * middleware function and invokes it on matching requests, where before F2
 * there was none. **That is not a choice.** `config.matcher` has to be a static
 * literal — Next parses it out of the file rather than evaluating it, and a
 * `matcher: FLAG ? [...] : []` fails the build with "Unsupported node type
 * ConditionalExpression at config.matcher". So the matcher is unconditional and
 * the *body* carries the flag. The cost is one pass-through invocation per
 * request until L1, and no change to what any request returns.
 *
 * The branch is taken once at module load rather than per request because
 * `NEXT_PUBLIC_AUTH_ENABLED` is inlined at build time and cannot change between
 * requests.
 *
 * ## The matcher
 *
 * Verbatim from Clerk's `clerkMiddleware()` reference: skip Next internals and
 * static assets, cover everything else, and always cover API routes and Clerk's
 * own `/__clerk/*` handshake paths even when they look like files.
 *
 * Note this is `middleware.ts`, not `proxy.ts` — Next 16 renames the file, and
 * this app is on Next 15. Renaming it belongs to any future Next 16 upgrade.
 */
const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

export default AUTH_ENABLED ? clerkMiddleware() : () => NextResponse.next();

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
