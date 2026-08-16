/**
 * Which credential goes to which endpoint — the post-L1 state.
 *
 * Card L1 executed the F3 §5 removal, so the interim C0 admin secret is gone
 * from the client entirely. What remains:
 *
 * 1. **No endpoint carries an admin header.** Not `/auth/*`, not `/portfolio/*` —
 *    even a build that still has the old `NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET`
 *    env var set sends nothing, because the code that read it is deleted.
 * 2. **The Clerk session token (via `withAuth`) is the only credential.** With
 *    sign-in on it is attached automatically; a signed-out visitor gets the
 *    backend's honest 401.
 * 3. **A flag-off build is locked.** With `NEXT_PUBLIC_AUTH_ENABLED` off there is
 *    no credential to send, so `/portfolio/*` calls short-circuit to `locked`.
 *
 * Driven through the real exported functions with a stubbed `fetch`, so the
 * assertions are about what leaves the browser.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ADMIN_HEADER = "x-alphadesk-admin-secret";

type Call = { url: string; init: RequestInit };

function stubFetch(status = 200, body: unknown = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
      } as unknown as Response;
    }),
  );
  return calls;
}

function headerOf(init: RequestInit, name: string): string | null {
  const headers = init.headers;
  if (!headers) return null;
  return new Headers(headers as HeadersInit).get(name);
}

async function loadApi(env: Record<string, string | undefined>) {
  vi.resetModules();
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) vi.stubEnv(key, "");
    else vi.stubEnv(key, value);
  }
  return import("@/lib/api");
}

beforeEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("linking is identity-bound", () => {
  it("never sends the admin secret to /auth/login", async () => {
    const calls = stubFetch(200, { authorization_url: "https://broker/authorize" });
    const api = await loadApi({ NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET: "operator-secret" });

    await api.startAuthLogin();

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain("/auth/login");
    expect(headerOf(calls[0].init, ADMIN_HEADER)).toBeNull();
  });

  it("never sends the admin secret to /auth/logout", async () => {
    const calls = stubFetch(200, {});
    const api = await loadApi({ NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET: "operator-secret" });

    await api.logoutAuth();

    expect(headerOf(calls[0].init, ADMIN_HEADER)).toBeNull();
  });

  it("no longer sends the admin header to /auth/status (removed at L1)", async () => {
    const calls = stubFetch(200, { authenticated: true });
    const api = await loadApi({ NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET: "operator-secret" });

    await api.getAuthStatus();

    // The F3 §5 removal: even with the old env var set, no admin header leaves.
    expect(headerOf(calls[0].init, ADMIN_HEADER)).toBeNull();
  });
});

describe("/portfolio/* credentials", () => {
  it("never sends an admin header, even with the old env var set (removed at L1)", async () => {
    const calls = stubFetch(200, { user_id: "local" });
    const api = await loadApi({
      NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET: "operator-secret",
      NEXT_PUBLIC_AUTH_ENABLED: "true",
    });

    await api.getPortfolioSummary();

    expect(headerOf(calls[0].init, ADMIN_HEADER)).toBeNull();
  });

  it("is a locked build when sign-in is not compiled in", async () => {
    stubFetch();
    const api = await loadApi({ NEXT_PUBLIC_AUTH_ENABLED: undefined });

    await expect(api.getPortfolioSummary()).rejects.toMatchObject({ code: "locked" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("makes the request anyway once sign-in is compiled in", async () => {
    // The whole point of the change: with a session available, a build with no
    // operator secret is a normal build, not a locked one.
    const calls = stubFetch(200, { user_id: "user_2abc" });
    const api = await loadApi({
      NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET: undefined,
      NEXT_PUBLIC_AUTH_ENABLED: "true",
    });

    await api.getPortfolioSummary();

    expect(calls).toHaveLength(1);
    expect(headerOf(calls[0].init, ADMIN_HEADER)).toBeNull();
  });

  it("reports 401 as unauthorized rather than as a locked build", async () => {
    stubFetch(401, { detail: "Not signed in." });
    const api = await loadApi({ NEXT_PUBLIC_AUTH_ENABLED: "true" });

    await expect(api.getPortfolioSummary()).rejects.toMatchObject({
      code: "unauthorized",
      status: 401,
    });
  });
});
