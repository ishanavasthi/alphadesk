import { defineConfig } from "vitest/config";
import path from "node:path";

/**
 * The repo's first frontend test runner (card S1).
 *
 * Kept deliberately small: no plugin stack, no global setup file beyond the one
 * jsdom shim React needs, and no coverage thresholds. Its whole job right now is
 * two behaviours that were previously verified by hand with DevTools open — the
 * sector drill-down race guard (D1) and the staleness banner (S1) — so that
 * "re-run the manual procedure" becomes `npm test`.
 *
 * Notes for whoever extends it:
 *
 * - `jsx: "automatic"` is set here because `tsconfig.json` says
 *   `"jsx": "preserve"` (Next transforms it itself). esbuild reads that tsconfig
 *   and would otherwise leave JSX in the output for Node to choke on.
 * - `environment: "jsdom"` is global. If a future suite is pure logic and slow
 *   because of it, use a per-file `// @vitest-environment node` docblock rather
 *   than splitting the config.
 * - `next/*` is not stubbed. These tests render leaf components and the page's
 *   own logic; the moment something needs the router, add a stub here rather
 *   than reaching for a full Next test harness.
 */
export default defineConfig({
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    setupFiles: ["tests/setup.ts"],
    restoreMocks: true,
  },
  resolve: {
    alias: { "@": path.resolve(__dirname) },
  },
});
