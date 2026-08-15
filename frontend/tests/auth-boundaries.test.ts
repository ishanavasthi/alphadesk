/**
 * Two structural invariants of card F2 that no render test can see.
 *
 * 1. **`useAuth` no longer comes from `AuthProvider`.** The rename exists
 *    because Clerk exports a hook of the same name; a single surviving import
 *    of the old name compiles, runs, and gates a page on the wrong question.
 * 2. **`@clerk/nextjs` is imported only from `components/clerk/` and
 *    `middleware.ts`.** That containment is the entire reason the flag-off
 *    bundle can be identical to the pre-F2 one — a stray import anywhere in the
 *    always-rendered tree links Clerk into the initial chunk and no test of
 *    behaviour would notice, because behaviour would be unchanged. Only the
 *    bytes would.
 *
 * Source-scanning tests rather than assertions on behaviour, deliberately: what
 * is being protected here *is* the shape of the source.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const SCANNED_DIRS = ["app", "components", "lib", "tests"];
const EXTENSIONS = new Set([".ts", ".tsx"]);

/** Every TypeScript source file in the app, as `[relative path, contents]`. */
function sources(): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      if (entry === "node_modules" || entry.startsWith(".")) continue;
      const full = path.join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (EXTENSIONS.has(path.extname(entry)))
        out.push([path.relative(ROOT, full), readFileSync(full, "utf8")]);
    }
  };
  for (const dir of SCANNED_DIRS) walk(path.join(ROOT, dir));
  out.push(["middleware.ts", readFileSync(path.join(ROOT, "middleware.ts"), "utf8")]);
  return out;
}

/** Import statements only — a mention inside a comment is documentation. */
function importedModules(contents: string): string[] {
  const found: string[] = [];
  const re = /(?:^|\n)\s*import[\s\S]*?from\s+["']([^"']+)["']|import\(\s*["']([^"']+)["']\s*\)/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(contents)) !== null) found.push(match[1] ?? match[2]);
  return found;
}

describe("the useAuth -> useIndMoney rename", () => {
  it("leaves no import of useAuth from AuthProvider anywhere", () => {
    const offenders = sources().filter(([, contents]) =>
      /import\s*\{[^}]*\buseAuth\b[^}]*\}\s*from\s*["'][^"']*AuthProvider["']/.test(contents),
    );
    expect(offenders.map(([file]) => file)).toEqual([]);
  });

  it("exports useIndMoney and no longer exports useAuth from AuthProvider", () => {
    const contents = readFileSync(path.join(ROOT, "components/AuthProvider.tsx"), "utf8");
    expect(contents).toMatch(/export function useIndMoney\(/);
    expect(contents).not.toMatch(/export function useAuth\(/);
  });
});

describe("Clerk containment", () => {
  const ALLOWED = (file: string) =>
    file.startsWith(`components${path.sep}clerk${path.sep}`) ||
    file === "middleware.ts" ||
    file.startsWith(`tests${path.sep}`);

  const importsClerk = ([, contents]: [string, string]) =>
    importedModules(contents).some((m) => m.startsWith("@clerk/"));

  it("has a detector that actually detects it", () => {
    // Positive control. Without this, a broken regex would report "no
    // offenders" forever and the invariant below would be worth nothing.
    const seen = sources().filter(importsClerk).map(([file]) => file);
    expect(seen).toContain(`components${path.sep}clerk${path.sep}ClerkIdentityProvider.tsx`);
    expect(seen).toContain("middleware.ts");
  });

  it("is imported only from components/clerk/ and middleware.ts", () => {
    const offenders = sources()
      .filter(([file]) => !ALLOWED(file))
      .filter(importsClerk)
      .map(([file]) => file);

    expect(offenders).toEqual([]);
  });

  it("is reached only through a flag-gated component", () => {
    // `Identity` is a server component (no "use client") so an unrendered
    // branch never ships its chunk; `UserMenu` sits under one and therefore has
    // to reach for `next/dynamic` instead. Both must consult the flag.
    for (const file of ["components/Identity.tsx", "components/UserMenu.tsx"]) {
      const contents = readFileSync(path.join(ROOT, file), "utf8");
      expect(contents, file).toMatch(/AUTH_ENABLED/);
    }
    expect(readFileSync(path.join(ROOT, "components/Identity.tsx"), "utf8")).not.toMatch(
      /^\s*["']use client["']/m,
    );
    expect(readFileSync(path.join(ROOT, "components/UserMenu.tsx"), "utf8")).toMatch(
      /dynamic\(/,
    );
  });
});

describe("lib/api.ts", () => {
  const api = readFileSync(path.join(ROOT, "lib/api.ts"), "utf8");

  it("routes every backend call through the token-attaching wrapper", () => {
    // A bare `fetch(` at an API_BASE call site would silently skip identity —
    // the exact failure this wrapper exists to make impossible. The pattern is
    // "whatever word precedes the opening paren", so both the offender and the
    // wrapper are counted and the two are told apart by name rather than by a
    // negative lookbehind nobody can read.
    const callers = [...api.matchAll(/(\w+)\(\s*`\$\{API_BASE\}/g)].map((m) => m[1]);
    expect(callers.length).toBeGreaterThan(5); // the detector found call sites at all
    expect([...new Set(callers)]).toEqual(["apiFetch"]);
    expect(api).toMatch(/async function apiFetch\(/);
    // And the wrapper is the one place the token is attached.
    expect(api).toMatch(/withAuth\(init\.headers\)/);
  });

  it("still sends the interim C0 admin header (F3 is what removes it)", () => {
    expect(api).toMatch(/x-alphadesk-admin-secret/);
  });
});
