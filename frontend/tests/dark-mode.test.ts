/**
 * Two structural invariants of the dashboard's dark variant.
 *
 * 1. **Nothing on the portfolio surface renders a raw colour.** A hard-coded
 *    hex is invisible in review — it looks correct, because it was authored
 *    against the light palette — and only shows up as a light patch on a dark
 *    page nobody screenshotted. Only the token file may name colours.
 * 2. **The dark block re-points every token the light block defines.** A token
 *    left out does not fail: it silently keeps its light value, so a single
 *    white card survives on a black ground. Comparing the two declaration sets
 *    is the only check that notices.
 *
 * Source scans rather than renders, deliberately: what is protected here is the
 * shape of the stylesheet, and a jsdom render resolves no cascade at all.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const CSS = path.join(ROOT, "app/portfolio/portfolio.css");
const EXTENSIONS = new Set([".ts", ".tsx"]);

/** Every source file on the portfolio surface, as `[relative path, contents]`. */
function surfaceSources(): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (EXTENSIONS.has(path.extname(entry)))
        out.push([path.relative(ROOT, full), readFileSync(full, "utf8")]);
    }
  };
  walk(path.join(ROOT, "components/portfolio"));
  walk(path.join(ROOT, "app/portfolio"));
  return out;
}

/** The custom properties declared inside the first `{ … }` after `selector`. */
function declaredTokens(css: string, selector: string): string[] {
  const start = css.indexOf(selector);
  expect(start, `${selector} not found in portfolio.css`).toBeGreaterThanOrEqual(0);
  const block = css.slice(start, css.indexOf("}", start));
  return [...block.matchAll(/^\s*(--[\w-]+):/gm)].map((match) => match[1]);
}

describe("dark mode", () => {
  it("names no colour outside the token file", () => {
    const offenders = surfaceSources()
      .filter(([, source]) => /#[0-9a-fA-F]{3,8}\b/.test(source.replace(/\/\*[\s\S]*?\*\//g, "")))
      .map(([file]) => file);
    expect(offenders).toEqual([]);
  });

  it("re-points every light token in the dark block", () => {
    const css = readFileSync(CSS, "utf8");
    const light = declaredTokens(css, "[data-adp] {");
    const dark = declaredTokens(css, '[data-adp][data-adp-theme="dark"] {');
    // --radius is a measurement, not a colour, and is the one token the dark
    // block deliberately inherits.
    expect(light.filter((token) => token !== "--radius" && !dark.includes(token))).toEqual([]);
  });
});
