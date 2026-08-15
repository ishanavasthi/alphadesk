# D0 — dashboard design bake-off

Five complete, deliberately different treatments of the same portfolio
dashboard, all rendering the **same synthetic dataset** (`demo-data.js`,
derived from `backend/tests/fixtures/demo/`; the 26-week history is invented
and labeled as such). Open any file directly in a browser — no build step.

Every demo covers the full D1 surface: net-worth header (invested vs current,
absolute + %), allocation by asset type and sector (sorted single-hue bars —
identity lives in labels, per the dataviz method), market-cap mix (ordered
sequential strip, OKLab-monotonic ramps), the 26-week trend line with
crosshair + tooltip, a sortable holdings table, and the honest null states:

- unknown cost basis → **"—"** (Balanced Advantage Fund row — never −100%),
- real basis with value gone to zero → a **legitimate −100%** (Gamma Nano Fund),
- source-reported bucket with zero rows → the **EPF empty-state** callout,
- US exposure flagged by badge (no currency field exists upstream — C2).

| File | Direction | One line |
| --- | --- | --- |
| `a-shadcn.html` | **shadcn/ui** (required direction) | Zinc system-UI cards, quiet and product-neutral; what AlphaDesk looks like on stock shadcn. |
| `b-terminal.html` | **Terminal** (required direction) | The current Bloomberg aesthetic evolved: dark, dense, amber, eyebrow labels, ticker tape, corner-ticked panels, command bar. |
| `c-passbook.html` | **Passbook ledger** | Indian bank-passbook vernacular: ruled ledger rows, margin rule, serif + mono figures, balance-in-words, rubber stamp. |
| `d-annual.html` | **Annual report** | Editorial: giant Helvetica hero as a typographic equation, numbered exhibits, International Klein Blue, generous air. |
| `e-brutalist.html` | **Brutalist blocks** | Thick borders, hard shadows, yellow highlight, allocation as a proportional block mosaic. |

Screenshots for the record live in the session scratchpad (not committed —
the repo's no-binaries rule exists so the HF Space can deploy; see
`docs/STATUS.md` deploy notes).

**Gate:** the operator picks one. On choice: `DECISION.md` here records the
locked design (tokens, layout, per-component notes), `V2_PLAN.md` §2 gets the
decision row, orchestrator memory records it, and losing demos move to
`rejected/`. Until then no real dashboard frontend is written.
