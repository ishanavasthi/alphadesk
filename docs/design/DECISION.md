# D0 decision — locked 2026-08-16

**Winner: the shadcn/ui direction** (`a-shadcn.html`), chosen by the operator.
Losing demos live in `rejected/` for the record. The direction was then
extended across the full product surface — the four reference pages below are
the visual contract for D1 and U1. **Implement them faithfully; anything they
leave ambiguous goes back to the orchestrator, not into the code.**

| Reference | Surface it locks |
| --- | --- |
| `a-shadcn.html` | Portfolio dashboard: stat cards, trend, allocations, cap strip, sortable holdings table, null states |
| `a2-overview.html` | AI overview panel (narrative + metric chips + agent chips + degraded state), staleness banner, top-bar actions |
| `a3-insights.html` | Metric tiles w/ threshold gauges, concentration curve, SIP health table, projection mock (future-labeled), range tabs |
| `a4-shell.html` | Landing, /demo banner, connect gate + consent list, Lab entry, empty state, account menu (incl. Delete my data) |

## Implementation stack (D1/U1)

Real **shadcn/ui** (Tailwind, `components.json`), base color **zinc**,
radius **0.5rem**. Charts: **Recharts**, styled to match the demos' SVG
treatments. The demos are the source of truth for look; shadcn components are
the implementation vehicle.

## Tokens (from `shadcn.css` — the canonical file)

- Ground `#fafafa` · card `#ffffff` · border `#e4e4e7` · ink `#09090b`
  · muted `#71717a` · faint `#a1a1aa`
- Accent (charts, links, primary emphasis) `#2563eb` (blue-600)
- P&L: good `#059669` · bad `#dc2626` — **status colors never used as chart
  series colors**
- Warn banner: bg `#fffbeb` · border `#fde68a` · ink `#92400e`
- Cap-band sequential ramp (ordered L→M→S): `#1d4ed8` → `#60a5fa` → `#bfdbfe`
  (OKLab-monotonic, validated)
- Type: system sans (`ui-sans-serif, -apple-system, …`); numerals always
  `font-variant-numeric: tabular-nums`; page title 20/600 -0.02em; card
  headers 14/600; stat values 24/600; body 14; captions 12 muted
- Radius 8px cards / 6px buttons / 999px chips; shadow `0 1px 2px rgba(0,0,0,.04)`

## Chart rules (binding, from the dataviz pass)

- Allocation (asset type, sector): **sorted horizontal single-hue bars**,
  accent fill on `#f4f4f5` track, label left / `₹value · weight%` right.
  Identity lives in labels — never a multi-hue categorical palette.
- Market cap: stacked strip on the sequential ramp above, 2px gaps, legend
  chips below. The live source can return FOUR bands (Mega + Large/Mid/Small):
  sample the ramp per band count with per-channel-monotonic interpolation —
  at three bands the locked hexes reproduce exactly (amended 2026-08-16, D1
  review).
- Trend: 2px accent line, 7% opacity area, emphasized endpoint dot,
  crosshair + tooltip on hover, y-axis in lakh (`10.2L`), synthetic/paused
  state labeled in the caption.
- Tooltips: ink-950 bg, white 12px text, 6px radius.

## Conventions (binding)

- INR everywhere: `Intl.NumberFormat('en-IN')`, ₹ prefix, no decimals on
  amounts; signed values use +/− with color.
- Null states: unknown cost basis renders **"—"** with the tooltip "Cost
  basis not reported by the source" — never a computed −100%. A real
  wipe-out (basis known, value 0) DOES show −100%. Source-empty buckets get
  the dashed `empty` callout naming the gap (EPF pattern).
- US exposure: `US` badge (blue-50 bg / blue-700 ink / blue-200 border) on
  the holding name.
- Badges: `type` (zinc), `good`, `warn`, `lab` (purple — every Lab surface),
  `soon` (dashed — future features).
- Buttons: primary = ink-950; accent = blue-600 (link/CTA moments);
  outline; ghost; destructive text-red. Small = 4px/10px padding.
- AI overview: narrative claims carry inline **metric chips** (blue-50 pill
  with the exact figure); the computed-metrics rail lists every number the
  narrative may cite; agent chips show the fan-out; the degraded state
  ("AI overview unavailable — every number still renders") is part of the
  component, not an afterthought.
- Staleness: amber banner, `⏸ History paused — last captured N days ago`,
  with primary "Capture now".
- Footer on every page: `Synthetic demo data` (demo only) `· descriptive
  analytics only · not investment advice` + Privacy/Terms links.
- Focus visible (2px accent outline), reduced-motion respected, tables
  scroll in their own container — no page-level horizontal scroll at 375px.

## Dark variant (added 2026-08-16, issue #8)

Dark is an **additive variant of the direction locked above, not a second
direction**: the same zinc family, the same measurements, radii, type scale
and chart rules. Only the token *values* change, on
`[data-adp][data-adp-theme="dark"]` in `frontend/app/portfolio/portfolio.css`.
No component branches on the theme — a component that needs to know which
theme it is in is a component that has escaped the token set.

Scope is every `[data-adp]` surface — the dashboard, `/demo`, the marketing
pages and, since #18, the Lab. (Before #18 the Lab kept its own dark terminal
chrome; see "The Lab joins the direction" below.)

Behaviour: the OS preference is the default, a toggle in the dashboard top bar
overrides it and persists in `localStorage["adp-theme"]`, and an inline script
in the portfolio layout applies the attribute before first paint so neither
theme flashes. With no stored choice the surface keeps following the OS live.

| Token | Light | Dark |
| --- | --- | --- |
| ground / `--background` | `#fafafa` | `#09090b` |
| ink / `--foreground` | `#09090b` | `#f5f5f5` |
| card, popover | `#ffffff` | `#131316` |
| border, input | `#e4e4e7` | `#27272b` |
| secondary / muted / accent | `#f4f4f5` | `#1d1d20` |
| muted ink | `#71717a` | `#9c9ca5` |
| primary / on-primary | `#18181b` / `#ffffff` | `#f5f5f5` / `#121216` |
| ring | `#2563eb` | `#3b82f6` |
| `--adp-accent` | `#2563eb` | `#3b82f6` |
| `--adp-accent-soft` / `-ring` / `-strong` | `#eff6ff` / `#bfdbfe` / `#1d4ed8` | `#1e2a4a` / `#1d4ed8` / `#60a5fa` |
| `--adp-good` / `--adp-bad` (P&L) | `#059669` / `#dc2626` | `#34d399` / `#f87171` |
| `--adp-faint` | `#a1a1aa` | `#52525b` |
| `--adp-track` / `--adp-hairline` | `#f4f4f5` | `#1c1c1f` |
| warn bg / bd / ink | `#fffbeb` / `#fde68a` / `#92400e` | `#2a2205` / `#854d0e` / `#fbbf24` |
| `good` badge bg / bd / ink | `#ecfdf5` / `#a7f3d0` / `#047857` | `#052e22` / `#065f46` / `#6ee7b7` |
| `lab` badge bg / bd / ink | `#faf5ff` / `#e9d5ff` / `#7e22ce` | `#2a1240` / `#6b21a8` / `#d8b4fe` |
| chip ink (metric chip, `US` badge) | `#1d4ed8` | `#93c5fd` |
| narrative prose ink | `#27272a` | `#d4d4d8` |
| tooltip bg / ink | `#09090b` / `#ffffff` | `#f4f4f5` / `#09090b` |
| cap ramp L → M → S | `#1d4ed8` → `#60a5fa` → `#bfdbfe` | `#93c5fd` → `#3b82f6` → `#1e3a8a` |

The cap ramp is walked the other way on dark — light to dark instead of dark to
light — so lightness stays monotonic across the ordered bands in both themes.
Bands beyond three still sample the ramp by per-channel interpolation
(`color-mix(in srgb, …)` over the tokens), which reproduces the locked three
exactly.

## The Lab joins the direction (locked 2026-09-11, issue #18)

**Winner: `lab/a-console.html` — "Desk Console"**, chosen by the operator from a
five-way bake-off (`docs/design/lab/`, losers in `lab/rejected/`). The Lab's
dark Bloomberg terminal is retired: it renders inside the same `[data-adp]`
token surface as the dashboard, light and dark, and **the direction above is
unchanged** — this is a surface joining it, not an amendment to it.

The reference page is the visual contract for the Lab the way `a-shadcn.html` is
for the dashboard. What it locks:

- **Chrome.** The dashboard's top bar — wordmark, `Portfolio / Lab` nav, theme
  toggle, IND Money link chip, account menu. No second chrome.
- **The simulation band.** Directly under the top bar on every `/lab` view: the
  purple `lab` badge plus *"A live simulation. Runs aren't saved. Not investment
  advice; no orders are placed."* on the `lab` badge tokens. It is the Lab's
  identity — carried by a label, never by a private palette.
- **Pipeline.** Five equal cells on one bordered strip, left to right, each with
  the agent's name, its output count and its elapsed time, and a 2px accent rule
  under the finished ones. Order encodes the real dependency chain, so the
  sequence is information, not decoration.
- **Candidates.** Split by outcome, never mixed: **Cleared the guardrails** as a
  three-up card grid (the three sector slots), **Not staged** as a two-up
  compact card carrying only the verdict and the reason. A rejection is a
  result, so it is shown, never hidden.
- **Conviction and evidence, always together, never against a threshold.**
  The bake-off mock drew confidence against a 0.70 floor and a 0.75 pass line;
  **B11 landed between the mock and the port and removed that reading.** It
  measured the model and found rerun noise larger than the between-stock spread
  — there is no cut point, the surviving thresholds are a collapse detector, and
  the number is a self-assessment of *direction*, not a quality score. So the
  meter carries no ticks: threshold marks would be the most confident-looking
  thing on the card and the least true. Conviction is labelled as a
  self-assessment and drawn beside `evidence_quality`, which is low by
  construction while RAG is dormant — one without the other is the presentation
  B11 exists to stop. The verdict is the badge's job, and `data_gaps` says what
  would have made the call better. See `docs/SPECS/B11.md`.
  *(`lab/a-console.html` predates this and still shows the ticks. Per the usual
  rule, where the demo and the shipped Lab disagree, the shipped Lab wins.)*
- **The gate.** The human-approval banner sits on the warn tokens above the
  candidates and is the loudest element on the view; approval itself is the
  standard dialog.

### Two amendments the Lab needs

Both are extensions of existing families, declared once in `portfolio.css`:

| Token | Light | Dark | Why |
| --- | --- | --- | --- |
| `--adp-bad-bg` / `-bd` / `-ink` (`bad` badge) | `#fef2f2` / `#fecaca` / `#b91c1c` | `#2a0f12` / `#7f1d1d` / `#fca5a5` | A risk verdict of REJECT had no badge tint; built on the `good` badge recipe. |
| `--adp-warn-mark` | `#d97706` | `#fbbf24` | The warn family is a background, a border and an ink — no value reads as *amber* filling an 8px meter or a 7px dot, and `--adp-warn-ink` used that way reads brown. **A mark only: it never sets text.** |

`up` / `down` / `flag` / `cyan`, `.eyebrow`, `.pill-*`, `.hero-glow`, `.caret`
and `.bg-up-soft` are gone with the terminal.
