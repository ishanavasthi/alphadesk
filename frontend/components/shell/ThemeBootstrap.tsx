"use client";

import { useEffect } from "react";

/** Where the choice lives. Same key `ThemeToggle` writes. */
const STORAGE_KEY = "adp-theme";
/** The `[data-adp]` wrapper the token sets hang off. */
const ROOT_ID = "adp-root";

/**
 * The pre-paint half, inlined as a string so it runs before the first paint of
 * a *document* load. Byte-for-byte the rule `applyStoredTheme` below applies: a
 * stored choice wins, and its absence follows the OS.
 */
const INLINE = `(function(){try{var r=document.getElementById("${ROOT_ID}");if(!r)return;var s=localStorage.getItem("${STORAGE_KEY}");if(s==="dark"||(s!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches))r.setAttribute("data-adp-theme","dark")}catch(e){}})()`;

/** The mount half. Same rule, and it also *clears* a stale dark. */
function applyStoredTheme(): void {
  const root = document.getElementById(ROOT_ID);
  if (!root) return;
  let dark = false;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    dark =
      stored === "dark" ||
      (stored !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  } catch {
    // Storage refused. Falling through with `dark = false` renders light, which
    // is the same answer the inline script gives when it throws.
  }
  if (dark) root.setAttribute("data-adp-theme", "dark");
  else root.removeAttribute("data-adp-theme");
}

/**
 * Keeps `data-adp-theme` on `#adp-root` correct across both ways a themed
 * surface can appear.
 *
 * **Document load** — the inline `<script>` runs before the first paint, so
 * there is no light flash to correct on hydration. This is what the marketing
 * and dashboard layouts already did, and it is unchanged.
 *
 * **Client-side route change** — the inline script does *not* cover this, and
 * that gap was a real bug. Each themed surface owns its own `#adp-root`, so
 * moving between route groups (`/` → `/demo`) unmounts one wrapper and mounts
 * another. React re-inserts this `<script>` element on that mount, but the
 * browser does not execute an inline script inserted through `innerHTML`, so
 * the new wrapper stayed bare: a reader who picked dark got a light `/demo`, and
 * then a light landing page on the way back, while `localStorage` still said
 * `dark`. The `useEffect` closes it — mounting the wrapper is exactly the moment
 * the attribute needs re-deriving.
 *
 * The effect is idempotent with the script, so the load path does no extra work
 * and never flashes. It runs on mount only: nothing else can change the answer
 * without also remounting (`ThemeToggle` writes the attribute itself, and the
 * OS-preference listener lives with the toggle).
 */
export function ThemeBootstrap() {
  useEffect(applyStoredTheme, []);
  return <script dangerouslySetInnerHTML={{ __html: INLINE }} />;
}
