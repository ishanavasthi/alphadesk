/**
 * The dashboard's theme survives Portfolio → Lab → Portfolio.
 *
 * `/lab` is a different route group with its own shell, so bouncing through it
 * unmounts `app/portfolio/layout.tsx`'s `#adp-root` and mounts a brand-new one
 * on the way back. The chosen theme is not React state — it is the
 * `data-adp-theme` attribute on that element — and the layout used to set it
 * with nothing but an inline `<script dangerouslySetInnerHTML>`. That script
 * runs once per *document* load: React re-creates the element on a client-side
 * remount, but the browser never executes an inline script inserted that way, so
 * the fresh wrapper came back bare and a reader who picked dark got a light
 * dashboard while `localStorage` still said `dark`.
 *
 * Rendering the real layout is the point of this file. `ThemeBootstrap`'s own
 * mount behaviour is already covered in `theme-continuity.test.tsx`; what was
 * broken here was this layout not using it, which only a test of the layout
 * itself can catch. Against the pre-fix layout the remount assertion fails.
 */

import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PortfolioLayout from "@/app/portfolio/layout";

// The layout's data half is irrelevant to the theme and would otherwise pull in
// the whole fetch stack. Stubbed to pass children straight through so the tree
// under test is exactly the wrapper, the bootstrap, and nothing else.
vi.mock("@/components/portfolio/PortfolioProvider", () => ({
  PortfolioProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/app/portfolio/PortfolioShell", () => ({
  PortfolioShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// jsdom in this runner exposes no `window.localStorage`, and the bootstrap
// treats a throwing storage as "no choice" — which would make the assertion
// below pass for the wrong reason. Same in-memory stand-in as
// `theme-continuity.test.tsx`, kept local for the same reason.
const store = new Map<string, string>();
Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => void store.set(key, String(value)),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
    key: (index: number) => [...store.keys()][index] ?? null,
    get length() {
      return store.size;
    },
  },
});

afterEach(() => window.localStorage.clear());

/** The wrapper as it currently exists in the document, if it does. */
const root = () => document.getElementById("adp-root");

describe("the portfolio layout re-applies the stored theme on remount", () => {
  it("comes back dark after an unmount and remount", () => {
    window.localStorage.setItem("adp-theme", "dark");

    // Portfolio.
    const first = render(<PortfolioLayout>{null}</PortfolioLayout>);
    expect(root()?.getAttribute("data-adp-theme")).toBe("dark");

    // → Lab: the App Router drops this layout entirely.
    first.unmount();
    expect(root()).toBeNull();

    // → back to Portfolio: a fresh wrapper, no document load, no script run.
    render(<PortfolioLayout>{null}</PortfolioLayout>);
    expect(root()?.getAttribute("data-adp-theme")).toBe("dark");
  });

  it("still ships the pre-paint inline script for a full document load", () => {
    // The mount effect corrects a remount; only the inline script can beat the
    // first paint of a hard load. Removing it would trade this bug for a flash.
    const { container } = render(<PortfolioLayout>{null}</PortfolioLayout>);
    const script = container.querySelector("script");
    expect(script?.innerHTML).toContain('getElementById("adp-root")');
    expect(script?.innerHTML).toContain('localStorage.getItem("adp-theme")');
  });
});
