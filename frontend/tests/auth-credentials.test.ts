/**
 * Which credential goes to which endpoint, after card F3 made the backend
 * per-user.
 *
 * Three rules, and each of them is a security decision rather than a style one:
 *
 * 1. **`/auth/login` and `/auth/logout` never carry the admin secret.** The
 *    backend refuses it there, and it should never be offered: a link made
 *    under a shared operator secret has no owner, which is the process-wide
 *    credential F3 deleted.
 * 2. **`/portfolio/*` still carries it when the build has one.** Sign-in is off
 *    in production until card L1, so this is the operator's only way in.
 * 3. **A missing admin secret is not a locked build once sign-in is on.** The
 *    Clerk token becomes the credential, and refusing to make the request would
 *    render "locked" at a visitor who simply needs to sign in.
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

  it("does send it to /auth/status, which is a read and per-caller", async () => {
    const calls = stubFetch(200, { authenticated: true });
    const api = await loadApi({ NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET: "operator-secret" });

    await api.getAuthStatus();

    expect(headerOf(calls[0].init, ADMIN_HEADER)).toBe("operator-secret");
  });
});

describe("/portfolio/* credentials", () => {
  it("sends the interim admin secret when the build has one", async () => {
    const calls = stubFetch(200, { user_id: "local" });
    const api = await loadApi({ NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET: "operator-secret" });

    await api.getPortfolioSummary();

    expect(headerOf(calls[0].init, ADMIN_HEADER)).toBe("operator-secret");
  });

  it("is a locked build when there is no secret and no sign-in", async () => {
    stubFetch();
    const api = await loadApi({
      NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET: undefined,
      NEXT_PUBLIC_AUTH_ENABLED: undefined,
    });

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
