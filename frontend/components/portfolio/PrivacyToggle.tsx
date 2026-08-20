"use client";

import { Eye, EyeOff } from "lucide-react";

import { Button } from "./ui";
import { toggleAmountsHidden, useAmountsHidden } from "./privacy";

/**
 * Hide every rupee amount on the surface — the control people reach for when
 * someone is beside them, or a screen is being shared, or a screenshot is about
 * to be taken.
 *
 * The icon shows the **action**, not the state: eye-off means "press to hide",
 * so what the button offers is always what its glyph depicts. `aria-pressed`
 * carries the state instead, which is what a screen reader announces and what
 * the accompanying text spells out — an icon-only control whose meaning inverts
 * silently is the classic version of this bug.
 *
 * Unlike `ThemeToggle` this subscribes to React state, because the flag has to
 * reach pure formatter functions rather than a CSS attribute; `privacy.ts`
 * explains why the value itself lives at module scope.
 */
export function PrivacyToggle() {
  const hideAmounts = useAmountsHidden();

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={toggleAmountsHidden}
      aria-pressed={hideAmounts}
      aria-label={hideAmounts ? "Show amounts" : "Hide amounts"}
      title={
        hideAmounts
          ? "Amounts are hidden. Percentages, weights and the trend line are unaffected."
          : "Hide every rupee amount on this page — percentages and the trend line stay visible."
      }
    >
      {hideAmounts ? (
        <Eye className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <EyeOff className="h-3.5 w-3.5" aria-hidden />
      )}
    </Button>
  );
}
