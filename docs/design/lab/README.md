# Lab bake-off — bringing the product theme into the Lab

> **DECIDED 2026-09-11: `a-console.html` (Desk Console) won**, chosen by the
> operator. `../DECISION.md` now carries the locked Lab section and is the
> binding contract; this directory is the record of the choice. The losing four
> live in `rejected/`.
>
> Issue [#18](https://github.com/ishanavasthi/alphadesk/issues/18). The
> direction runs one way: **the Lab adopts the product theme**, not the other
> way around. These five are treatments of the Lab in the locked
> shadcn/zinc/blue language of the landing page and the dashboard.

Open any file directly in a browser — no build step. Each one has a **Theme**
button in the top bar; the page follows your OS preference until you press it.

## What is fixed, and what is being chosen

**Fixed in all five** — they all `<link>` [`../shadcn.css`](../shadcn.css), the
canonical token file behind [`../DECISION.md`](../DECISION.md). Same ground,
card, border and ink; same `#2563eb` accent; same `#059669` / `#dc2626` P&L
pair; same 8px card / 6px button / 999px chip radii; same system-sans type
scale and tabular numerals; same buttons, badges, banners and table treatment.
`lab.css` adds only the dark values from DECISION's dark-variant table and
fixes the literals `shadcn.css` hardcoded, so both themes resolve.

**Being chosen: the information architecture.** What is the Lab, structurally —
a console, a pipeline, a ledger, a queue, or a report? Each answer moves the
pipeline, the candidates and the approval gate to different places.

| File | Direction | One line |
| --- | --- | --- |
| [`a-console.html`](a-console.html) | **Desk Console** ✅ | The straight port. Page title, a horizontal five-step strip, candidates as a card grid — drop it next to `/portfolio` and there is no seam. |
| [`b-runrail.html`](rejected/b-runrail.html) | **Run Rail** | Keeps the current Lab's one good idea — a vertical pipeline you watch fill — rebuilt in product tokens. Results are full-width rows beside it. |
| [`c-ledger.html`](rejected/c-ledger.html) | **Candidate Ledger** | Table-first, the holdings table's sibling: one sortable row per candidate, the brief folded inside it. The densest of the five. |
| [`d-queue.html`](rejected/d-queue.html) | **Approval Queue** | Built around the only thing the Lab asks of you. Master list left, full brief right, a standing bar that always says what will be written and to how many names. |
| [`e-brief.html`](rejected/e-brief.html) | **Research Brief** | The run produces a document, in the AI-overview language from `a2-overview.html`: narrative with inline metric chips, an agent rail, a figures rail, numbered entries. |

## The same run in every one

One synthetic run, so the five are compared on form and nothing else:
query *"oversold pharma large-caps with a catalyst"*, run `a7f3c1d9`, 38.4s —
**18 scanned → 6 researched → 5 calls → 3 cleared, 2 rejected → paused at the
human gate.** The five candidates exercise every guardrail in
`backend/agents/risk_manager.py` at once:

| | Call | Verdict | Confidence | Why |
| --- | --- | --- | --- | --- |
| SUNPHARMA | buy | PASS | 0.82 | Above the 0.75 pass line; sector slot 1 of 3 |
| CIPLA | buy | PASS | 0.76 | Above the pass line; slot 2 of 3 |
| DRREDDY | buy | FLAG | 0.73 | Caution band, 0.70–0.75; slot 3 of 3 |
| LUPIN | buy | REJECT | 0.79 | **Sector cap** — outscores two cleared names and is still stopped |
| AUROPHARMA | hold | REJECT | 0.68 | **Below the 0.70 floor**; issued no target, so the figure reads "—" |

Company names are real; every figure is invented and labelled as such.
LUPIN is deliberately in there: a design that can't explain why a 0.79 lost to
a 0.73 isn't finished.

Each file also carries the states strip — query desk, run in flight, IND Money
not connected (409), nothing cleared, approved, and the run lost to a backend
restart — plus the approval dialog.

## Non-negotiables, honoured in all five

- The **live-simulation** label sits directly under the top bar on every view,
  carrying the purple `lab` badge, and the footer keeps
  `descriptive analytics only · not investment advice`.
- Every surface says the destination is a **paper** watchlist and that no order
  is placed.
- PASS / FLAG / REJECT keep their semantic colour, and those colours are used
  as status only — never as a series colour.
- The approval gate is the loudest element on the results view.

## Two things DECISION doesn't have

Building these turned up exactly two gaps in the token set. Both are declared
once in `lab.css`, and adopting any of the five means adopting them as DECISION
amendments rather than letting inline hexes back into the code.

- **`.badge.bad` — a REJECT tint.** DECISION defines `type`, `good`, `warn`,
  `lab` and `soon`; a risk verdict of REJECT has nowhere to go. Declared on the
  same recipe as `.badge.good`: light `#fef2f2` / `#fecaca` / `#b91c1c`, dark
  `#2a0f12` / `#7f1d1d` / `#fca5a5`.
- **`--warn-mark` — a mid amber.** The warn family is a background
  (`#fffbeb`), a border (`#fde68a`) and an ink (`#92400e`); there is no value
  that reads as *amber* when it fills an 8px meter or a 7px dot, and `--warn-ink`
  used that way reads brown. `--warn-mark` is `#d97706` on light, `#fbbf24` on
  dark — the missing step of the same family. It is a **mark only**: it never
  sets text, which stays `--warn-ink`.

## A position worth noticing

Every candidate draws the analyst's confidence against the two lines the Risk
Manager actually enforces — the **0.70 floor** and the **0.75 pass line** — as
ticks on the meter, rather than printing a bare percentage. It is the one place
these mocks add information the current Lab doesn't show, and it is what makes
a FLAG legible as "cleared, barely" instead of a colour you have to remember.

## As shipped

`a-console.html` is the look; `../DECISION.md` stays the binding token contract.
Anything the shipped Lab and this demo disagree on, the shipped Lab wins.
