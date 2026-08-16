"use client";

import { useEffect } from "react";
import { Moon, Sun } from "lucide-react";

import { Button } from "./ui";

/** Where the choice lives, and what the bootstrap in `layout.tsx` reads. */
const STORAGE_KEY = "adp-theme";
/** The `[data-adp]` wrapper the token sets hang off (`app/portfolio/layout.tsx`). */
const ROOT_ID = "adp-root";

type Theme = "light" | "dark";

/** The explicit choice, or `null` when the reader has never made one. */
function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function applyTheme(theme: Theme) {
  const root = document.getElementById(ROOT_ID);
  if (!root) return;
  if (theme === "dark") root.setAttribute("data-adp-theme", "dark");
  else root.removeAttribute("data-adp-theme");
}

/**
 * Light ↔ dark for the dashboard surface.
 *
 * It holds **no React state**: the current theme is the attribute on the
 * wrapper, which the inline bootstrap already set before this component
 * existed, and the two icons are both rendered with CSS hiding the wrong one
 * (`portfolio.css`). A `useState` version would have to guess the theme during
 * SSR, render that guess, and correct it on hydration — the exact flash the
 * bootstrap exists to prevent.
 *
 * The media listener matters for the no-choice case: someone who has never
 * pressed this button is following the OS, so the surface should follow it when
 * it changes rather than freeze on whatever it was at page load. A stored
 * choice suppresses that — it is an override, and an override that gets
 * silently undone is not one.
 */
export function ThemeToggle() {
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) => {
      if (storedTheme() === null) applyTheme(event.matches ? "dark" : "light");
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const toggle = () => {
    const dark = document.getElementById(ROOT_ID)?.getAttribute("data-adp-theme") === "dark";
    const next: Theme = dark ? "light" : "dark";
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage refused: the flip still applies to this page, it just will not
      // survive a reload. Better than a button that does nothing.
    }
    applyTheme(next);
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={toggle}
      aria-label="Switch between light and dark"
      title="Switch between light and dark. Without a choice here, the dashboard follows your system setting."
    >
      <Sun className="adp-icon-light h-3.5 w-3.5" aria-hidden />
      <Moon className="adp-icon-dark h-3.5 w-3.5" aria-hidden />
    </Button>
  );
}
