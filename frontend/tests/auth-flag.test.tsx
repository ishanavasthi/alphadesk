/**
 * Card F2's central promise, as tests: **with `NEXT_PUBLIC_AUTH_ENABLED` off,
 * nothing about this app changes.**
 *
 * The flag is read at module scope, so every case here re-imports the module
 * under test after stubbing the environment — `vi.resetModules()` before each
 * dynamic `import()`. A test that imported at the top of the file would pin
 * whichever value the runner happened to start with.
 *
 * `@clerk/nextjs` is mocked throughout. That is not a convenience: mounting a
 * real `<ClerkProvider>` would need a live Clerk instance, and the thing worth
 * asserting is *whether Clerk is reached for at all*, which a mock answers
 * exactly.
 */

import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const clerkProviderMounted = vi.fn();
const userButtonMounted = vi.fn();
const getToken = vi.fn(async () => "clerk-session-token");
let signedIn = false;

vi.mock("@clerk/nextjs", () => ({
  ClerkProvider: ({ children }: { children: ReactNode }) => {
    clerkProviderMounted();
    return <div data-testid="clerk-provider">{children}</div>;
  },
  useAuth: () => ({ getToken }),
  useUser: () => ({ isLoaded: true, isSignedIn: signedIn }),
  useClerk: () => ({ signOut: vi.fn() }),
  UserButton: Object.assign(
    () => {
      userButtonMounted();
      return <div data-testid="clerk-user-button" />;
    },
    {
      MenuItems: ({ children }: { children: ReactNode }) => <>{children}</>,
      Action: () => null,
    },
  ),
  SignInButton: ({ children }: { children: ReactNode }) => <>{children}</>,
  SignIn: () => <div data-testid="clerk-sign-in" />,
  Waitlist: () => <div data-testid="clerk-waitlist" />,
}));

/** Records what `next/dynamic` was asked to load, without loading it. */
const dynamicCalls: Array<() => Promise<unknown>> = [];
vi.mock("next/dynamic", () => ({
  default: (loader: () => Promise<unknown>) => {
    dynamicCalls.push(loader);
    return function DynamicStub() {
      return <div data-testid="dynamic-slot" />;
    };
  },
}));

function setFlag(value: string | undefined) {
  vi.resetModules();
  dynamicCalls.length = 0;
  if (value === undefined) vi.stubEnv("NEXT_PUBLIC_AUTH_ENABLED", "");
  else vi.stubEnv("NEXT_PUBLIC_AUTH_ENABLED", value);
}

beforeEach(() => {
  signedIn = false;
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

// --------------------------------------------------------------------------- //
// The flag itself
// --------------------------------------------------------------------------- //
describe("AUTH_ENABLED", () => {
  it.each([
    ["true", true],
    ["false", false],
    ["", false],
    ["TRUE", false],
    ["1", false],
    ["yes", false],
  ])("is %j -> %s", async (value, expected) => {
    setFlag(value);
    const { AUTH_ENABLED } = await import("@/lib/auth");
    expect(AUTH_ENABLED).toBe(expected);
  });

  it("is off when the variable is not set at all", async () => {
    setFlag(undefined);
    const { AUTH_ENABLED } = await import("@/lib/auth");
    expect(AUTH_ENABLED).toBe(false);
  });
});

// --------------------------------------------------------------------------- //
// <Identity> — the provider gate in app/layout.tsx
// --------------------------------------------------------------------------- //
describe("<Identity>", () => {
  it("renders children with no Clerk provider when the flag is off", async () => {
    setFlag("false");
    const { Identity } = await import("@/components/Identity");
    render(
      <Identity>
        <p>the app</p>
      </Identity>,
    );

    expect(screen.getByText("the app")).toBeTruthy();
    expect(screen.queryByTestId("clerk-provider")).toBeNull();
    expect(clerkProviderMounted).not.toHaveBeenCalled();
  });

  it("mounts <ClerkProvider> around the children when the flag is on", async () => {
    setFlag("true");
    const { Identity } = await import("@/components/Identity");
    render(
      <Identity>
        <p>the app</p>
      </Identity>,
    );

    const provider = screen.getByTestId("clerk-provider");
    expect(clerkProviderMounted).toHaveBeenCalledTimes(1);
    // The children stay *inside* the provider — a provider rendered as a
    // sibling would type-check, render, and quietly give every hook below it
    // the signed-out answer.
    expect(provider.textContent).toContain("the app");
  });

  it("registers a session-token getter with lib/api only when enabled", async () => {
    setFlag("false");
    const off = await import("@/lib/auth");
    const { Identity: OffIdentity } = await import("@/components/Identity");
    render(<OffIdentity>x</OffIdentity>);
    expect(await off.sessionToken()).toBeNull();

    setFlag("true");
    const on = await import("@/lib/auth");
    const { Identity: OnIdentity } = await import("@/components/Identity");
    render(<OnIdentity>x</OnIdentity>);
    expect(await on.sessionToken()).toBe("clerk-session-token");
  });
});

// --------------------------------------------------------------------------- //
// <UserMenu> — the top-bar gate, which lives under a client component
// --------------------------------------------------------------------------- //
describe("<UserMenu>", () => {
  it("renders nothing and never asks for the Clerk chunk when the flag is off", async () => {
    setFlag("false");
    const { UserMenu } = await import("@/components/UserMenu");
    const { container } = render(<UserMenu />);

    expect(container.innerHTML).toBe("");
    // The point of `next/dynamic` here: with the flag off the loader is never
    // even constructed, so the chunk cannot be requested by any code path.
    expect(dynamicCalls).toHaveLength(0);
  });

  it("loads the Clerk menu as a dynamic chunk when the flag is on", async () => {
    setFlag("true");
    const { UserMenu } = await import("@/components/UserMenu");
    render(<UserMenu />);

    expect(screen.getByTestId("dynamic-slot")).toBeTruthy();
    expect(dynamicCalls).toHaveLength(1);
    await expect(dynamicCalls[0]()).resolves.toBeTypeOf("function");
  });
});

describe("<ClerkUserMenu>", () => {
  it("offers a sign-in control when signed out", async () => {
    setFlag("true");
    signedIn = false;
    const { ClerkUserMenu } = await import("@/components/clerk/ClerkUserMenu");
    render(<ClerkUserMenu />);

    expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(userButtonMounted).not.toHaveBeenCalled();
  });

  it("shows the account button when signed in", async () => {
    setFlag("true");
    signedIn = true;
    const { ClerkUserMenu } = await import("@/components/clerk/ClerkUserMenu");
    render(<ClerkUserMenu />);

    expect(screen.getByTestId("clerk-user-button")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// withAuth() — what every backend request carries
// --------------------------------------------------------------------------- //
describe("withAuth", () => {
  it("returns the caller's headers untouched when the flag is off", async () => {
    setFlag("false");
    const { setSessionTokenGetter, withAuth } = await import("@/lib/auth");
    // Even with a getter registered — the flag wins.
    setSessionTokenGetter(async () => "would-be-token");

    const headers = { "x-alphadesk-admin-secret": "s3cret" };
    expect(await withAuth(headers)).toBe(headers);
    expect(await withAuth(undefined)).toBeUndefined();
  });

  it("adds the bearer token and keeps existing headers when enabled", async () => {
    setFlag("true");
    const { setSessionTokenGetter, withAuth } = await import("@/lib/auth");
    setSessionTokenGetter(async () => "tok-abc");

    const merged = new Headers(
      (await withAuth({ "x-alphadesk-admin-secret": "s3cret" })) as HeadersInit,
    );
    expect(merged.get("Authorization")).toBe("Bearer tok-abc");
    // The interim C0 header must survive: F3, not F2, is what removes it.
    expect(merged.get("x-alphadesk-admin-secret")).toBe("s3cret");
  });

  it("sends no Authorization header when nobody is signed in", async () => {
    setFlag("true");
    const { setSessionTokenGetter, withAuth } = await import("@/lib/auth");
    setSessionTokenGetter(async () => null);

    const headers = { "Content-Type": "application/json" };
    expect(await withAuth(headers)).toBe(headers);
  });

  it("survives a getter that throws", async () => {
    setFlag("true");
    const { setSessionTokenGetter, sessionToken, withAuth } = await import("@/lib/auth");
    // Clerk Core 3's getToken throws `clerk_runtime_not_browser` outside the
    // browser. A request going out unauthenticated is a recoverable state; an
    // exception escaping into every fetch in the app is not.
    setSessionTokenGetter(() => {
      throw new Error("clerk_runtime_not_browser");
    });

    expect(await sessionToken()).toBeNull();
    const headers = { "Content-Type": "application/json" };
    expect(await withAuth(headers)).toBe(headers);
  });
});
