# Document background and scrolling

The theme used to apply only inside `[data-adp]`. The document retained a light
body background, a transparent root and the default overscroll behavior, leaving
light areas around the dark surface when mobile Safari reached the page boundary.

`app/globals.css` now gives the root a background and color scheme matching the
active surface. `:has([data-adp][data-adp-theme="dark"])` follows the existing
bootstrap/toggle attribute; it introduces no additional theme state or hydration
mutation. Root `overscroll-behavior-y: none` suppresses vertical elastic scrolling
and browser pull-to-refresh on supporting browsers. Ordinary vertical scrolling
and local horizontal table scrolling are preserved. Older browsers that ignore
overscroll behavior can still expose a correctly colored document background.

Run from `frontend`:

```bash
npx playwright install --with-deps chromium webkit
npm run test:browser
npm test
npm run build
```

`tests/browser/document-theme.spec.ts` uses the real theme bootstrap, toggle and
styles on a tall mobile surface. It checks stored-theme precedence, live system
changes, toggles, surface remounts, document/body colors and the root color scheme.
It also verifies overscroll suppression is applied and that normal scrolling still
reaches the bottom without horizontal overflow. All three tests fail before the
fix. The existing 14 Top movers cases run in both browsers too: 34 browser checks.

Linux WebKit verifies CSS behavior, not iOS Safari's native toolbar or touch bounce.
On an iPhone, check the live portfolio in both themes: scroll to the top and bottom,
try dragging beyond each boundary, toggle the theme and navigate between surfaces.
The document should stay the same ground color as the page, without a white gutter
in dark mode. Content should remain scrollable normally.
