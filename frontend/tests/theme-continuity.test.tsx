/**
 * The theme survives a client-side route change.
 *
 * The chosen theme is not React state — it is the `data-adp-theme` attribute on
 * `#adp-root`, put there before first paint by an inline `<script>`. That script
 * runs once per *document* load, which is fine until the router swaps one layout
 * for another without one: leaving the marketing group for `/demo` unmounts
 * `#adp-root`, and coming back remounts it bare. React re-inserts the `<script>`
 * element on that remount but the browser does not execute an inline script
 * inserted that way, so the attribute never comes back and a reader who picked
 * dark is silently returned to light — with `localStorage` still saying `dark`.
 *
 * Two invariants close that, and both are asserted here:
 *
 * 1. `ThemeBootstrap` re-applies the stored choice **on mount**, so a remounted
 *    wrapper is themed even though no document load happened.
 * 2. Every layout that scopes the token set with `data-adp` also carries
 *    `id="adp-root"` *and* applies the stored choice. A surface with the palette
 *    but no way to read the choice (which is what `/demo` was) can only ever
 *    render light.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ThemeBootstrap } from "@/components/shell/ThemeBootstrap";

const ROOT = path.resolve(__dirname, "..");

/** Every `app/` + `components/` source that scopes the palette, as [path, source]. */
function sourcesScoping(marker: string): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      if (entry === "node_modules") continue;
      const full = path.join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.tsx$/.test(entry)) {
        const source = readFileSync(full, "utf8");
        // The attribute as it is written in JSX, not the string in a comment or
        // a CSS selector.
        if (new RegExp(`<[^>]*\\b${marker}\\b`, "s").test(source))
          out.push([path.relative(ROOT, full), source]);
      }
    }
  };
  walk(path.join(ROOT, "app"));
  walk(path.join(ROOT, "components"));
  return out;
}

/** A remounted wrapper: the palette scope is there, the attribute is not. */
function mountBareRoot(): HTMLElement {
  const root = document.createElement("div");
  root.id = "adp-root";
  root.setAttribute("data-adp", "");
  document.body.appendChild(root);
  return root;
}

// jsdom in this runner exposes no `window.localStorage` at all, and the
// component treats a throwing storage as "no choice" — which would make every
// assertion below pass for the wrong reason. An in-memory stand-in keeps the
// storage branch the thing under test. Local to this file on purpose: a shim in
// `setup.ts` would change behaviour for suites that never asked for it.
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

/** Force the OS preference jsdom's stub reports, for the no-choice case. */
function setSystemDark(dark: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: dark && query.includes("dark"),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

afterEach(() => {
  window.localStorage.clear();
  document.getElementById("adp-root")?.remove();
});

describe("ThemeBootstrap re-applies the stored theme on mount", () => {
  it("restores dark on a wrapper that mounted without the attribute", () => {
    window.localStorage.setItem("adp-theme", "dark");
    const root = mountBareRoot();

    render(<ThemeBootstrap />, { container: root });

    expect(root.getAttribute("data-adp-theme")).toBe("dark");
  });

  it("clears a stale dark attribute when the stored choice is light", () => {
    window.localStorage.setItem("adp-theme", "light");
    const root = mountBareRoot();
    root.setAttribute("data-adp-theme", "dark");

    render(<ThemeBootstrap />, { container: root });

    expect(root.getAttribute("data-adp-theme")).toBeNull();
  });

  it("follows the OS when the reader has never chosen", () => {
    setSystemDark(true);
    const root = mountBareRoot();

    render(<ThemeBootstrap />, { container: root });

    expect(root.getAttribute("data-adp-theme")).toBe("dark");
    setSystemDark(false);
  });

  it("leaves a stored choice alone when it disagrees with the OS", () => {
    setSystemDark(true);
    window.localStorage.setItem("adp-theme", "light");
    const root = mountBareRoot();

    render(<ThemeBootstrap />, { container: root });

    expect(root.getAttribute("data-adp-theme")).toBeNull();
    setSystemDark(false);
  });
});

describe("every themed surface can read the stored choice", () => {
  // `data-adp` is what scopes the palette. A surface that opts into it and then
  // cannot read the choice renders the light half of a two-half token set for
  // everyone — which is exactly what `/demo` did. Scanned rather than listed so
  // a themed surface added later cannot quietly skip the wiring.
  const THEMED = sourcesScoping("data-adp");

  /**
   * The one deliberate exception. `/sign-in` and `/waitlist` render a Clerk
   * form, and Clerk's default appearance is light; theming the shell around a
   * light card would look broken, not dark. It takes the palette for the footer
   * and stays light on purpose — see the component's own comment.
   */
  const LIGHT_ON_PURPOSE = new Set(["components/shell/AuthFooterShell.tsx"]);

  it("finds the themed surfaces to check", () => {
    // A rename that empties the scan would make every assertion below vacuous.
    expect(THEMED.map(([file]) => file).sort()).toEqual([
      "app/(marketing)/layout.tsx",
      "app/demo/layout.tsx",
      "app/portfolio/layout.tsx",
      "components/shell/AuthFooterShell.tsx",
    ]);
  });

  it.each(THEMED)("%s carries id=adp-root and applies the stored theme", (file, source) => {
    if (LIGHT_ON_PURPOSE.has(file)) {
      // Assert the exemption is still what it claims: no theme wiring at all,
      // rather than half of it.
      expect(source).not.toMatch(/id="adp-root"/);
      expect(source).not.toMatch(/ThemeBootstrap/);
      return;
    }

    expect(source, `${file} has no #adp-root for the theme to hang off`).toMatch(
      /id="adp-root"/,
    );
    // Either the shared component or the surface's own inline bootstrap — both
    // read `adp-theme` from storage and set the attribute.
    expect(
      /<ThemeBootstrap\s*\/>/.test(source) || /localStorage\.getItem\("adp-theme"\)/.test(source),
      `${file} never applies the stored theme`,
    ).toBe(true);
  });
});
