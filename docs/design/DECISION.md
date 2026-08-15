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
