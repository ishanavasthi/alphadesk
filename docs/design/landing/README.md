# Landing-page bake-off (design/landing-experiments)

> **DECIDED 2026-08-16: `c-prospectus.html` (Zinc Prospectus) won**, chosen by
> the operator — and **shipped the same day** in PR #23
> (`ishanavasthi/landing-redesign`, merge `953fb0b`). This directory is now the
> historical record of that choice, not a pending proposal: the live landing is
> `frontend/components/landing/` composed by
> `frontend/components/shell/LandingHero.tsx`, and two of those source files
> cite `c-prospectus.html` by path as their design source. Losing demos live in
> `rejected/` for the record; `rejected/d-controlroom.html` and
> `rejected/e-bahikhata.html` were caught mid-way through the v1→v2 content
> pivot when the decision landed and retain some v1 research-desk copy (visuals
> complete, content partially stale).

Five complete, deliberately different landing-page treatments for **AlphaDesk
v2** — the portfolio analyzer (`V2_PLAN.md` §1): sign in (waitlist-gated),
link IND Money, see net worth / allocation / holdings / daily snapshot
history, plus an AI overview that narrates *verified computed numbers*. The
research desk appears only as the clearly-labelled **Lab / Simulation**
secondary section on every page — never the hero. Built with a vibe-discovery
method: each variant gets a named aesthetic derived from a real-world
reference, a collision of two influences, and one wildcard. Open any file
directly in a browser — no build step. Google Fonts load over the network
where used; every page degrades to system fallbacks offline.

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
| `c-prospectus.html` | **Zinc Prospectus** | **Shipped.** Locked shadcn/zinc/blue tokens from `../DECISION.md`, hero carries a faithful mini dashboard mock — adopting it cost nothing. |
| `d-controlroom.html` | **Approval Interlock** | Mission control × railway interlocking: animated SVG schematic where only computed metrics pass the gate into the narrative. |
| `e-bahikhata.html` | **Bahi Khata** | 1950s red cloth-bound trading ledger: daily snapshot rows as ledger entries, rubber-stamped `PAPER ONLY` on the Lab folio. |

## As shipped

`c-prospectus.html` is the look; `docs/design/DECISION.md` stays the binding
token contract. The rebuild is `072e276` (sections), `83f7574` (theme toggle
moved into `SiteHeader`) and `3bd4751` (theme choice carried across
client-side navigation), merged with the L1 legal expansion `830a8f7`.

Section-for-section the page follows the demo — hero + dashboard mock, trust
band, feature bento, five-step flow, Lab/Simulation block, closing CTA — with
four deliberate deviations:

- **`BrokersSection` is new.** The demo named IND Money only inside the flow
  copy; the shipped page gives the read-only broker link its own block.
- **The demo's footer fine print became `MarketingFooter`** — same binding
  line, plus the L1 `/privacy` and `/terms` links and the open-source repo
  link, per the L1 requirement that legal is reachable from every page.
- **Colours resolve through the DECISION tokens** on the `[data-adp]`
  wrapper rather than the demo's own CSS, so the landing inverts with the
  dashboard's dark variant with no theme branch of its own.
- **`authEnabled` gates the waitlist CTA** in both the hero and the closing
  block: `/waitlist` is a Clerk route that `notFound()`s while
  `NEXT_PUBLIC_AUTH_ENABLED` is off, so flag-off the live demo is the single
  public entry point.

Treat the demos as history. Anything the shipped page and a demo disagree on,
the shipped page wins — re-deriving copy or layout from these files will
reintroduce pre-launch framing that L1 and PR #23 deliberately moved past.
