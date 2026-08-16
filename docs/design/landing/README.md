# Landing-page bake-off (design/landing-experiments)

> **DECIDED 2026-08-16: `c-prospectus.html` (Zinc Prospectus) wins**, chosen
> by the operator. Losing demos live in `rejected/` for the record; note that
> `rejected/d-controlroom.html` and `rejected/e-bahikhata.html` were caught
> mid-way through the v1→v2 content pivot when the decision landed and retain
> some v1 research-desk copy (visuals complete, content partially stale).
> Implementation plan: the landing is rewritten in `frontend/` on a dedicated
> branch off `main`, after which this experiment branch is history.

Five complete, deliberately different landing-page treatments for **AlphaDesk
v2** — the portfolio analyzer (`V2_PLAN.md` §1): sign in (waitlist-gated),
link IND Money, see net worth / allocation / holdings / daily snapshot
history, plus an AI overview that narrates *verified computed numbers*. The
research desk appears only as the clearly-labelled **Lab / Simulation**
secondary section on every page — never the hero. Built with the project
skill `.claude/skills/landing-page-design/SKILL.md` (vibe-discovery method:
each variant gets a named aesthetic derived from a real-world reference, a
collision of two influences, and one wildcard). Open any file directly in a
browser — no build step. Google Fonts load over the network where used;
every page degrades to system fallbacks offline.

All copy is honest by construction and sourced from `V2_PLAN.md`: no
fabricated testimonials, press logos, user counts, or return claims. The
social-proof slot carries trust badges instead (read-only broker access ·
descriptive, never advisory · tokens encrypted at rest · delete-my-data
built in). CTAs are the U1 landing pair — **View the live demo** (`/demo`,
public, sample data) and **Join the waitlist** — and every page ends with
the binding footer line `descriptive analytics only · not investment
advice`, with all illustrative numbers labelled synthetic.

| File | Vibe | One line |
| --- | --- | --- |
| `a-broadsheet.html` | **Dalal Broadsheet** | Pink-paper Indian financial daily: Fraunces masthead, column rules, the framing rules as a double-ruled public notice. |
| `b-nightdesk.html` | **Night Desk** | Dealing room at 2am: Bloomberg terminal × Swiss poster; the hero types out the 23:45 IST snapshot run and the AI-overview fan-out. |
| `c-prospectus.html` | **Zinc Prospectus** | The on-brand candidate: locked shadcn/zinc/blue tokens from `../DECISION.md`, hero carries a faithful mini dashboard mock — adopting it costs nothing. |
| `d-controlroom.html` | **Approval Interlock** | Mission control × railway interlocking: animated SVG schematic where only computed metrics pass the gate into the narrative. |
| `e-bahikhata.html` | **Bahi Khata** | 1950s red cloth-bound trading ledger: daily snapshot rows as ledger entries, rubber-stamped `PAPER ONLY` on the Lab folio. |

**Gate:** the operator picks one. Implementation is explicitly deferred until
the current V2 plan's scope is complete — on choice we write an
implementation plan first; nothing here touches `frontend/` (U1/F2 own it),
`docs/design/DECISION.md` (the locked dashboard contract), `V2_PLAN.md`, or
`docs/STATUS.md`. Losing demos move to `rejected/` when the pick is made.
