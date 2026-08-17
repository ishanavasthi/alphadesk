/**
 * The privacy toggle: hide every rupee amount on the portfolio surface.
 *
 * The state lives at **module scope**, not in React, because `format.ts` is a
 * set of pure functions called during render — they cannot read a hook. The
 * provider owns a matching piece of React state whose only job is to re-render
 * the subtree after this flag flips; the formatters then read the new value on
 * their way through. Nothing is memoised under `PortfolioProvider`, so one
 * re-render reaches every number on the page.
 *
 * **Why there is no inline bootstrap here, unlike the theme.** The theme has one
 * because it changes the very first painted pixel. This does not: the surface
 * renders no numbers on the server (`phase` starts `loading` — `lastKnown` is
 * module memory and a server has none), so the first paint that contains an
 * amount happens on the client, after this module has already initialised from
 * storage. There is no frame in which a real balance is visible.
 *
 * Storage is `localStorage`, which is a deliberate departure from the holdings
 * cache next door: that one refuses `localStorage` because holdings are the most
 * sensitive thing this app touches. This is a boolean that reveals nothing, and
 * a privacy toggle that forgets itself on every reload is worse than no toggle.
 */

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "adp-privacy";

/** What a masked amount reads as. Dots, not a blur — see `format.ts`. */
export const MASK = "••••••";
/** The masked y-axis tick: a full-width dot run would swamp a narrow gutter. */
export const MASK_SHORT = "•••";

type Listener = () => void;

const listeners = new Set<Listener>();

function stored(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

/**
 * Read once at import, which on the client is before the first render that
 * could contain a number. On the server this is `false` and nothing renders an
 * amount anyway, so hydration agrees with the markup it is hydrating.
 */
let hidden = stored();

/** Are amounts currently hidden? Read by the formatters on every call. */
export function amountsHidden(): boolean {
  return hidden;
}

export function setAmountsHidden(next: boolean): void {
  if (next === hidden) return;
  hidden = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next ? "on" : "off");
  } catch {
    // Storage refused (private mode, blocked cookies): the flip still applies
    // to this page, it just will not survive a reload. A button that hides
    // nothing would be the worse failure.
  }
  listeners.forEach((listener) => listener());
}

/** Subscribe to flips. Used by the provider to re-render the surface. */
export function subscribeAmountsHidden(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Flip it. */
export function toggleAmountsHidden(): void {
  setAmountsHidden(!hidden);
}

/**
 * Subscribe a component to the flag.
 *
 * Deliberately **not** routed through `PortfolioContext`: the AI overview needs
 * this too, and it is otherwise independent of the dashboard's data context —
 * it takes what it needs as props and is rendered on its own in tests. Reaching
 * for the portfolio context there would couple a panel to a provider it does
 * not need, to read a boolean.
 *
 * The server snapshot is `false`, which is what the server renders anyway: the
 * surface paints no amounts while `phase` is `loading`.
 */
export function useAmountsHidden(): boolean {
  return useSyncExternalStore(subscribeAmountsHidden, amountsHidden, () => false);
}

/** Test seam: forget the choice and the subscribers between test files. */
export function resetPrivacy(): void {
  hidden = false;
  listeners.clear();
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}
