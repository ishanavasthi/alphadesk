# AlphaDesk — Deferred features & ideas

Not scoped into the current plan. Everything here is parked deliberately, with
the reason it's parked and what has to be true before it's picked up.
`V2_PLAN.md` is the plan of record; this file is the queue behind it.

Items carry a **`B<n>` id** (`B1`, `B2`, …) once they're concrete enough to pick
up as a card — quote the id when scheduling one. Unnumbered sections below are
still ideas, not queued work.

Grilling session of 2026-08-14 settled the frame these are judged against:
public but **waitlist-gated**; **one normalized portfolio model** with per-source
connectors; **descriptive analytics only** in v2 — scenario projection is itself
deferred to this backlog (no forward forecasts, no instrument-level advice on
real holdings; `V2_PLAN.md` §8.3 is the wording of record).

---

## Top of queue

### B9 — FD data integrity (source is wrong; stop presenting it as ours) — #65
**Status:** filed 2026-08-21, **ahead of everything else in this file**. Live wrong
data on the production dashboard, and it silently corrupts stored history that
cannot be backfilled (the MCP is point-in-time).

Verified against the raw payloads in `snapshot_raw`: IND Money reports the FD
bucket as `invested 15,000 / market_value 10,162 / total_pnl -4,838 /
pnl_per -32.25`, and AlphaDesk passes those through unchanged — the mapping is
correct, the source is not. The loss is one deposit reported as ₹5,000 invested /
₹162 current, and `total_pnl` has been frozen at exactly −4,838 for five days.

Two worse symptoms found alongside it: the FD bucket **vanished entirely** on
2026-08-18 (a phantom −₹8,550 dip written into `snapshot_days.total_value`, with
`buckets_failed` NULL), and on 2026-08-20 it was inside `total_networth` but
missing from the `assets` breakdown. `services/snapshots.py` marks a bucket failed
only on throttle/unsupported/source-error — a bucket the vendor silently omits
reads as "sold everything", which defeats S1's "a partial day never passes for
complete".

Scope, acceptance criteria, the SQL to pull every payload, and the exact
`snapshot_raw` ids are in **#65**. Not to be confused with §"FD tracking" below,
which is the long-term fix (compute the value ourselves); B9 is about not lying
until then.

---

## Deferred connectors

### Groww
**Status:** deferred entirely — no Groww account to test against.

Verified 2026-08-14 (so it doesn't get re-researched):

- `https://mcp.groww.in/mcp` is a live MCP server. `GET` unauthenticated → 401;
  `/.well-known/oauth-protected-resource` →
  `{"resource":"https://mcp.groww.in/","authorization_servers":["https://api.groww.in/"]}`.
- Authorization server metadata at `https://api.groww.in/.well-known/oauth-authorization-server`:
  - `authorization_endpoint`: `https://groww.in/oauth/authorize`
  - `token_endpoint`: `https://api.groww.in/oauth2/v1/token`
  - `registration_endpoint`: `https://api.groww.in/oauth2/v1/register` (DCR supported)
  - `code_challenge_methods_supported`: `["plain","S256"]`
  - `token_endpoint_auth_methods_supported`: `["client_secret_basic"]`
- **`grant_types_supported`: `["authorization_code"]` only — no `refresh_token`.**
  A Groww link cannot silently refresh; it expires and the user must re-link.
  The connector abstraction must therefore model *link health* without assuming
  refreshability, and the UI needs a "re-link required" state.
- No `scopes_supported` and no `revocation_endpoint` advertised. Unlike IND
  Money there may be nothing to call on unlink — decide whether that's
  acceptable before shipping.
- `token_endpoint_auth_methods` is `client_secret_basic`, where the IND Money
  code posts `client_secret` in the body — the shared OAuth helper must support
  both.

**Pick up when:** a test Groww account exists, and the normalized model +
connector interface have shipped and survived at least one real user.

**Separate, do not confuse:** Groww's *Trading API* (`groww.in/trade-api`) is a
different product — API key + TOTP, and it **places orders**. All the public
"Groww MCP" GitHub projects wrap that, not the OAuth MCP above. Storing an
order-capable credential for other people is a risk class this project has not
accepted. If it's ever considered, it needs its own written decision.

### B4 — Fund reference data from an external source (AMFI / market API / own DB)

**Why.** B3's `Sub-Category`, `Assets Management Company` and `Assets Under
Management` group-by options, its `GROWTH` / `REGULAR` / `DIRECT` badges, and B2's
sub-category averages are all blocked on data the IND Money MCP does not put on a
holdings row. Rather than wait on the vendor, source it ourselves: fund *reference*
data is public, static-ish, and not user-specific, so it belongs in our own
database, refreshed on a schedule.

**Verified 2026-08-17** (so it doesn't get re-researched):

- **AMFI daily NAV file — `https://portal.amfiindia.com/spages/NAVAll.txt`** (the
  `www.amfiindia.com` path 302s here). `200`, `text/plain`, **1.65 MB, 17,795
  lines, 14,274 scheme rows**. Columns:
  `Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date`,
  with **category headers** (`Open Ended Schemes(Equity Scheme - Large Cap Fund)`)
  and **AMC headers** (`Axis Mutual Fund`) interleaved as section breaks —
  **51 AMCs, 92 distinct category headers**. This single free file carries
  sub-category, AMC, plan, ISIN and NAV at once.
- **`https://api.mfapi.in/mf/<scheme_code>`** — unofficial free AMFI wrapper.
  `200`, JSON. `meta` gives `fund_house`, `scheme_type`, `scheme_category`,
  `isin_growth`, `isin_div_reinvestment`; `data` is a **dated NAV series** —
  scheme 120389 returned **4,494 points back to 01-01-2013**. `.../mf` lists
  **37,764 schemes** (5.7 MB); `.../mf/search?q=` does name search.
- **AUM is the one piece not verified.** AMFI publishes scheme-wise average AUM
  separately; the disclosure URL guessed at during this probe **404'd**. Treat AUM
  as an open question, not a solved one, and probe it before promising the
  `Assets Under Management` group-by.

**The dated NAV series is the bigger prize.** It is the thing that makes a
**sub-category average return series computable by us** — average the member
funds' NAV series per category, per window — which is exactly what **B2**'s
comparison and its "how it would have performed otherwise" simulation need, and
what C2 proved the MCP will never supply. B2's remaining blocker after this card
is only the *user's own cashflows*, not the benchmark.

**The real risk is the join key, not the data.** M1: IND Money publishes **no
ISIN and no symbol** on a holdings row — only `investment` (display name, empty in
1 of 14 rows) and `investment_code` (vendor id). AMFI keys on scheme code + ISIN.
So unless something yields an ISIN or an AMFI scheme code, the join is **fuzzy
name matching over 14k schemes whose names differ only by plan and option**
("Axis Liquid Fund - Direct Plan - Growth Option" vs "- Direct Plan - Daily IDCW"),
and a mis-join silently attaches the wrong category, AMC and NAV to someone's real
holding. Design for it: exact-match first, a confidence score, and **no badge and
no group when the match is uncertain** — an unmatched row is an honest row.

Evidence the join is *worth* attempting: the reference design's `Axis Liquid Fund
GROWTH` shows **NAV 3146.98**, and AMFI scheme **120389** (Axis Liquid Fund -
Direct Plan - Growth Option) was **3146.9887 on 16-Aug-2026**. Exact to the paisa —
the two datasets do describe the same instrument, and the reference's badge
convention is visible too: `REGULAR` is called out, **Direct is the unmarked
default**. Once joined, plan is an *observation* (AMFI names it, and the ISIN
differs per plan), not the name-parsing inference B3 warns about.

**Settle these before scoping:**

- **The category vocabulary is dirty and must be normalized.** Among the 92
  headers: `Equity Scheme - Contra Fund` **and** `Equity Schemes - Contra Fund`;
  `Sectoral/ Thematic` **and** `Sectoral Fund` **and** `Thematic Fund`; `ELSS`
  **and** `ELSS- Tax Saver Fund`. Grouping on the raw string produces duplicate
  buckets and splits a category average in half. Needs a maintained map onto
  SEBI's scheme-categorization vocabulary, plus a loud "unmapped category" path.
- **Dead schemes stay in the file with stale dates** — scheme 128954 (Axis Liquid
  Bonus) carried `05-May-2020`. Every row's own `Date` is authoritative; never
  assume file-date == row-date, or a five-year-old NAV renders as today's.
- **Own the data; don't depend on a third party at request time.** AMFI is the
  primary source and should be the source of record. `mfapi.in` is an unofficial,
  free, no-SLA wrapper — fine for a **one-time history backfill**, wrong as a
  runtime dependency. After backfill, our own NAV history grows by appending the
  daily AMFI file, so the dependency disappears.
- **Infra already exists.** Postgres + Alembic + a `CRON_SECRET`-guarded internal
  endpoint on an IST schedule (S1). Shape: a `fund_reference` table (scheme code,
  ISIN, name, AMC, raw + normalized category, plan, option) and a `fund_nav`
  history table, filled by a daily job. 1.65 MB / 14k rows is a trivial ingest.
  Cross-user and non-personal, so unlike every other table it is **not** per-user
  and not in `DELETE /account`'s cascade.
- **Privacy: this is market data, not user data — keep it that way.** Any external
  lookup must send a **fund identifier only**; never a request body containing the
  user's positions. Ingesting into our own DB keeps it off the `/privacy`
  subprocessor list entirely (L1) — a hosted API called at request time would have
  to be added there. Check AMFI's terms before redistributing beyond display.
- **MF only.** Indian equities would need a different source (exchange/NSE data)
  and a different card; do not let this one quietly grow into it.

**Pick up when:** ideally *with* B2/B3's `get_mf_funds_details` spike, not after —
the spike decides how expensive this is. If that tool returns an ISIN or scheme
code, the join is exact and this card is a straightforward nightly ingest. If it
does not, this becomes the **only** path to sub-category/AMC/plan and the
fuzzy-match design above is the bulk of the work.

### Broker statement / CAS import
Chosen over per-broker integrations as the coverage mechanism: one parser
(NSDL/CDSL CAS, contract notes) covers Zerodha, Angel, Groww, and anything else,
with **zero third-party credentials held**. Also the natural home for the FD gap
below.

Known cost: CAS PDFs are password-protected, format-drifting, and per-depository.
Non-trivial parser + a "we may have mis-read your statement" review step.

---

## User-supplied holdings

### Manual investments
"People can add their own investment too." Anything the connectors can't see:
FDs, physical gold, unlisted equity, real estate, EPF held elsewhere.

Design constraints already agreed: manual rows are first-class rows in the same
normalized model (same aggregates, same AI metrics), which forces answers to
who computes their current value and how double-counting against a broker row is
prevented.

**First slice shipped as B10** (fixed deposits — see §"FD tracking" below).
Everything else here — gold, unlisted equity, real estate, EPF elsewhere — is
still parked: FDs were taken first precisely because their value is computable
from their terms, and every other class needs a price the user would have to
keep updating by hand.

### FD tracking

**Status:** picked up 2026-08-21 as **B10** — issue
[#68](https://github.com/ishanavasthi/alphadesk/issues/68) carries the fixed
contract. Specs: `docs/SPECS/B10.md`, `docs/TESTING/B10.md`. Manual entry only
(add/edit/delete an FD, accrued value computed from the terms); the vendor FD
bucket itself is still B9/#65.

IND Money's MCP is unreliable for FDs — **verified 2026-08-21 with payloads, not
just user-reported** (see B9 / #65: a ₹5,000 deposit valued at ₹162, a P&L frozen
for five days, and the whole bucket dropping out of two daily snapshots). That
evidence is the strongest argument yet for owning FD valuation ourselves.
FDs are the clearest case
for manual entry because their value is *computable*, not quoted: principal +
rate + compounding + start/maturity date → accrued value, no price feed needed.
Good first manual asset type for exactly that reason.

---

## Analytics & AI

### Portfolio projection
Scoped as **scenario arithmetic, not forecast**: user-set CAGR assumptions
(e.g. 8/12/15%), corpus over time, SIP contributions included. Labelled as
arithmetic on chosen assumptions. Explicitly *not* an AI prediction of returns.

### Goal tracking
"Retirement by 2050 needs ₹X; you're at Y% of the run-rate." Reuses the
projection engine and the snapshot history. High perceived value, low new
machinery.

### Allocation-drift alerts
User sets a target allocation; snapshots already run daily; alert when drift
exceeds a band. Cheap once `portfolio_snapshots` exists, and it's the feature
that gives daily snapshots a *user-facing* reason to exist beyond a trend line.

### B1 — Flow-aware net worth (attribute day-over-day change to *why* it moved)

**The gap.** S1 snapshots record **levels**, one row per user per IST day, and
every derived number (the trend line, A1's WoW delta, anything future) is a
difference between two levels. A level difference cannot tell market movement
apart from money moving. If the bank bucket goes ₹1,00,000 → ₹70,000 on the same
day a mutual-fund position gains ₹30,000, the truth is *one transfer and a flat
net worth*, but today it reads as a bank fall and an MF rise with no relationship
between them. The same conflation makes any "return" computed off snapshots wrong
whenever the user deposits, withdraws, or starts a SIP — which is most months.

**What's wanted.** A reconciliation layer over consecutive snapshots that splits
each day's Δ into three kinds:

1. **market movement** — same units, different price;
2. **external flow** — money entering or leaving the visible perimeter (salary
   into the bank, a withdrawal out of it);
3. **internal transfer** — one bucket down, another up, net ~zero (the bank →
   MF-order case above).

Then surface it: a trend line that separates "you earned this" from "you added
this", and a plain-language day note ("₹30k moved from bank into mutual funds").

**Why it's worth doing.** It's the honest-return prerequisite. D1 deliberately
ships **Return % only, no XIRR**, and A1 computes **no XIRR** — partly effort,
but partly because a money-weighted return is meaningless without a flow series.
This card is what would unblock that later, and it makes the daily snapshot
history worth keeping for something beyond a line that drifts.

**What's already in place** (don't re-derive):

- `snapshot_holdings` freezes `units`, `avg_cost`, `invested_amount` and
  `current_price` per row, so **for instrument buckets the split is computable
  without any new data**: units up ⇒ a buy, units flat + price moved ⇒ market.
  That is the tractable half and could ship alone.
- `snapshot_days.buckets_failed` already marks partial days, and
  `attributed_day` already owns the IST-day rule — attribution must ride both,
  not invent a second notion of "day".

**The hard parts — settle these before scoping:**

- **Cash and bank rows have no units.** A ₹30k fall is spending, a transfer to
  the broker, or a transfer somewhere invisible, and the snapshot cannot
  distinguish them. Any pairing of a fall in one bucket with a rise in another
  is an **inference**, not an observation, and must be labelled as one in the UI.
  Never assert a cause that wasn't observed.
- **Is there a transaction feed at all?** This wants a C2-style data spike
  against the IND Money MCP before any modelling: is order/transaction history
  exposed, at what granularity, for which asset types? The two SIP tools C2
  inventoried are the closest known thing. If real transactions are available,
  most of the inference above collapses into bookkeeping — a very different and
  much better card. **Do the spike first.**
- **Gaps are unattributable, and cannot be backfilled** — S1's MCP is
  point-in-time by design. A missing day (or a bucket in `buckets_failed`) makes
  the Δ across that window ambiguous; it must be recorded as unattributed, never
  silently spread across the gap.
- **Same-day netting is invisible.** Once-daily snapshots see net change only:
  sell ₹50k and buy ₹50k on the same day and the day looks idle.
- **`invested_amount == 0` means unknown cost basis** (M1), so it can't be used
  as a flow proxy; and all money stays `Decimal` — a flow series that rounds is
  a flow series that accumulates error.
- Framing holds: this is **descriptive accounting on observed data**, not advice
  and not a forecast.

**Pick up when:** the MCP transaction-history spike has an answer. Related:
**B2 — XIRR analysis** below (the same flow series is its hard prerequisite),
**Tax-lot / capital-gains view** below (blocked on the same missing history —
likely the same spike), **Allocation-drift alerts** (drift caused by a transfer
is not the same signal as drift caused by the market), and **Portfolio
projection** (SIP contributions belong in the same flow series).

### B2 — XIRR analysis vs. sub-category average (mutual funds)

**What's wanted** (user's framing, 2026-08-17). Money-weighted return (XIRR) for
the mutual-fund sleeve across several time periods, each fund benchmarked against
**its own sub-category average** — a large-cap fund measured against the "Large
Cap" sub-category average over the same window, not against a single blended
index. Three parts:

1. **Current performance** — XIRR per fund and for the MF sleeve as a whole, over
   multiple horizons, computed from *all* past transactions.
2. **Comparison** — beating / not beating the matched sub-category average, stated
   as a verdict per fund.
3. **Simulated performance** — the counterfactual: the same cashflows, on the same
   dates, into the sub-category average instead. "How your investments would have
   performed otherwise."

Vendor precedent (IND Money's own XIRR Analysis) also truncates history — it
considers pre-2015 transactions *as of* 2015 rather than dropping them.

**Blocked on exactly the same thing as B1, and C2 already proved it.** Do not
re-derive this:

- `xirr` is a real key on every holdings row and was **exactly `0` in 14 of 14**
  rows (MF 9/9, SA 3/3, US_STOCK 1/1, FD 1/1) — the vendor advertises the field in
  `networth_holdings`' own tool description and does not populate it.
- It cannot be computed client-side either: XIRR needs **dated** cashflows, the
  payloads carry **no date field at all**, and the 15-tool MCP inventory contains
  **no transaction-history, cashflow-ledger, or trade-book tool**. Both SIP tools
  returned 0 rows and, by their own descriptions, would carry a *forward*
  schedule (next execution, current month) — not the past-dated series XIRR needs.
- Consequence already locked into shipped scope: D1 and A1 display **simple
  cumulative return** (`pnl_per`, `return_percentage`) and must **not** label it
  XIRR. That stays true until this card unblocks.
- Full write-up: `docs/ind_money_payloads.md` §Q1.

**So the gate is B1's data spike, not a scoping decision.** If the MCP (or a
later connector, or CAS import) yields dated transactions, this card becomes
tractable bookkeeping; without them it is not buildable at any effort level.

**The benchmark half is separately unverified.** Sub-category averages need a
classification and a return series per sub-category. Two tools *look* like the
source — `get_mf_funds_details` (`includes` ∈ `fund_performance`,
`category_tables`) and `get_mf_by_category` (`sort_key` ∈ `returns_1yr` /
`returns_3yr` / `returns_5yr`, so category-level returns exist somewhere behind
it) — but **neither was captured in C2**, whose 67 payloads were snapshot +
holdings + breakdowns + SIP only. Their response shapes, the sub-category
vocabulary, and whether an *average* (vs a per-fund list) is exposed are all
unknown. Fold this into the same spike; **and note the vendor is no longer the
only route — B4 makes the benchmark computable from AMFI's own dated NAV series,
which would leave the user's cashflows as this card's sole remaining blocker.** and note `get_mf_by_category` currently
sits under "MF screener — out of scope" further down this file, so picking this
up promotes that wrapper.

**Settle these before scoping:**

- **A truncated series makes XIRR silently wrong.** Any cutoff (2015 or a
  connector's own retention limit) must seed the position at the cutoff date as an
  **opening inflow**, not drop it — otherwise the return is computed against a
  cost basis that never existed. Whatever cutoff we end up with must be stated in
  the UI, the way the vendor states theirs.
- **Sub-category matching is a claim about the fund**, and a wrong match produces
  a confident wrong verdict ("not beating its category") on someone's real money.
  Take the classification from the data source; never infer it from a fund's name.
- **The counterfactual is arithmetic, not advice.** Replaying the user's *own*
  past cashflows into a category average is descriptive accounting and fits
  `V2_PLAN.md` §8.3. "You should switch to fund X" is instrument-level advice on
  real holdings and stays out — the simulation compares against a *category
  average*, never against a nameable fund to buy.
- **Cash-like rows are N/A, not 0%** (C2): SA rows had `pnl_per == 0` because they
  have no return by nature. XIRR must exclude them, not average them in.
- **`invested_amount == 0` means unknown cost basis** (M1) — not zero cost.
- Money stays `Decimal`, and XIRR's root-finding must be tested against known
  answers, including the ugly cases (a series that changes sign more than once,
  a fully-redeemed fund, a first purchase inside the reporting window).
- **Scope MF only** to start. Sub-categories are an MF concept, and C2 found the
  account had zero `IND_STOCK` rows anyway.

**Pick up when:** B1's transaction-history spike returns dated cashflows. The
benchmark half no longer waits on the vendor — take it from **B4** (AMFI) or from
`get_mf_funds_details(category_tables)` / `get_mf_by_category`, whichever the
spike shows is cleaner. Related: **B1** (the flow series is the shared
prerequisite), **Tax-lot / capital-gains view** (same missing history), **MF
screener** (the wrapper this needs), **B3 — Holdings table v2** (its
sub-category / AMC / AUM group-by needs the same `get_mf_funds_details` spike).

### Tax-lot / capital-gains view
Realised vs unrealised, STCG/LTCG split, ITR season utility. Needs transaction
history the current tools may not expose — gated on the data spike.

### B8 — Top movers over a user-chosen period

**Status:** picked up 2026-08-21 — issue [#66](https://github.com/ishanavasthi/alphadesk/issues/66)
carries the settled contract; built on `feat/b8-top-movers` (backend + frontend
halves by parallel Opus agents, both suites green on the merged tree).

**What's wanted** (user's framing, 2026-08-21). "Which of my holdings moved the
most between date A and date B?" — a ranked gainers/losers list over an
arbitrary window the user picks (a preset — 1D / 1W / 1M / 3M / YTD — or two
explicit dates), not just the single net-worth line `/portfolio/history`
returns today. Answered from the captured snapshots, so it is history the user
already owns rather than a fresh source call.

**Why it's worth doing.** It is the first feature that reads
`snapshot_holdings` for anything, and the cheapest one: S1 has been freezing
`units`, `current_price`, `current_value` and `invested_amount` per row per day
since 2026-08-16, and nothing has ever queried it. Today the only way to answer
"what moved" is to hand-write SQL against Neon — which is exactly how this card
was written. It also gives the daily capture a second user-facing reason to
exist beyond the trend line.

**What's already in place** (don't re-derive):

- `snapshot_holdings` is keyed by `(source, external_id)` — M1's identity pair —
  which is stable across days and is what a two-day join must match on. It is
  **not** `symbol`: on IND Money, MF and SA rows carry `symbol = NULL`.
- `services.snapshots.history_points(session, user_id, days=…)` is the existing
  windowed read and the shape to follow — same `attributed_day` IST rule, same
  "no DB configured ⇒ honestly empty, never a 500" degradation
  (`/portfolio/history`).
- Display names are **not** in `snapshot_holdings` — they live only in
  `snapshot_raw.payload…rows[].investment`, which is **pruned at 90 days**. A
  movers view older than the prune horizon can render ids and nothing else.
  Either denormalize a `name` column onto `snapshot_holdings` going forward, or
  accept nameless history and say so. Decide before scoping, not after the first
  pruned window.

**The hard parts — settle these before scoping:**

- **Rank by what?** Percent and rupees disagree violently on a real portfolio.
  Over 2026-08-16 → 08-20 the largest *rupee* movers were a savings account
  (+₹16,488) and an FD, while the largest *percent* mover was a ₹0.94 Amazon
  fraction (+1.55%). Both readings are useless alone; the view needs both
  columns and probably a minimum-position floor before it ranks anything.
- **Bank, FD and cash rows are not movers.** They have no `units` and no
  `current_price` — their Δ is a deposit or a spend, i.e. B1's *flow*, not
  market movement. Mixing them into a "top movers" list asserts a market move
  that never happened. Either exclude non-priced buckets or label them as flow
  in a separate group — and prefer the price series (`current_price`), not
  `current_value`, wherever a price exists, so a top-up doesn't read as a gain.
  This is the same conflation **B1** exists to fix; B8 is the read-only,
  ship-now half of it.
- **Endpoints of the window may not exist.** A user can ask for a range whose
  first or last day was never captured (no snapshot before 2026-08-16 at all;
  the backend was restarted, the cron missed). Snap to the nearest captured day
  **and say which days were actually compared** — never silently widen the
  window or interpolate. Same rule for `buckets_failed` days: a bucket that
  failed on one endpoint is *unknown*, not flat.
- **Positions that appear or vanish mid-window have no percentage.** A holding
  bought after day A, sold before day B, or a bucket the source returned empty
  for (the FD bucket came back `{"rows": []}` on 2026-08-18 and 08-20 with
  `buckets_failed` NULL — an honest empty, not a failure) must render as
  "opened" / "closed" / "not held", never as +100% or −100%.
- **Framing holds** (`V2_PLAN.md` §8.3): descriptive arithmetic over the user's
  own captured history. It ranks what *did* happen; it does not rate, recommend
  or project.

**Sketch of the surface** (not locked): `GET /portfolio/movers?from=&to=&limit=`
alongside `/portfolio/history` — same identity, same rate limit, same
optional-DB degradation — returning per holding: id, name (where known), the two
compared dates, start/end price and value, Δ% and Δ₹, and a `basis` field of
`price` | `balance` | `opened` | `closed`. UI-wise it is a gainers/losers pair of
lists under the trend line, with the window control shared with the chart.

**Pick up when:** there is enough captured history for a window longer than a
week to mean anything (D+30 from first capture, so ~2026-09-15), or sooner if a
dashboard card wants it. Does **not** block on B1's transaction spike — the
priced-instrument half is computable from what S1 already stores, which is
precisely why it can ship first. Related: **B1** (the flow half of the same
question), **B5 — Day's P&L** (the 1D case of this card; if both ship they
should share one computation), **B6 — P&L treemap** (same per-holding Δ, drawn
instead of ranked), **B3 — Holdings table v2** (its rows are this card's rows).

---

## Dashboard & UI

### B3 — Holdings table v2 (search, weight, plan badges, group-by)

Reference design supplied 2026-08-17 (a mutual-fund holdings table): a per-row
line of **Name** + plan badges (`GROWTH`, `REGULAR`/`DIRECT`), **NAV**, **Units**,
**Invested Amt.**, **Current Value**, **Weight**, **P&L** (absolute + %), **XIRR**;
a search box over the rows; a sort indicator on any column (`Weight` descending in
the reference); a `See All` expander under a truncated list; and a **Group by:**
control offering `None` · `Category` · `Sub-Category` · `Assets Under Management` ·
`Assets Management Company`.

D1 already ships `HoldingsTable` with sorting, nulls-always-sink, the `US` badge,
type badges, and `—` + tooltip for unknown cost basis. This card is the **delta**,
and the delta splits cleanly into "free" and "needs data we do not have".

**Free today — every field already exists in the M1 model:**

| Reference column | M1 field | Note |
| --- | --- | --- |
| Name | `name` | `None` in 1 of 14 real rows — the row must still render and still be searchable |
| NAV | `current_price` | |
| Units | `units` | |
| Invested Amt. | `invested_amount` | `None` = unknown basis → `—`, never `0` |
| Current Value | `current_value` | The only always-required number |
| P&L (abs + %) | `pnl` / `pnl_pct` | Both `None` whenever basis is |
| Weight | *(see below)* | The vendor ships `holding_percent` per row |

So search + the weight column + `See All` are a UI card, not a data card, and
could ship on their own.

**Weight needs one decision, not one field.** The vendor's own `holding_percent`
is on every row, *and* weight is computable as `current_value / total`. **They will
not agree** — M1 §5: bucket totals do not reconcile with the sum of their rows
(the `US_STOCK_WALLET` gap, rows priced from different refreshes). Pick one
definition, name it in the column tooltip, and use it everywhere; showing a
vendor weight beside an AlphaDesk-computed total is how a table contradicts
itself. Also decide what "weight" means once the table is filtered or grouped —
share of the whole portfolio, or share of the visible group.

**Not free — three of the five group-by options have no field behind them:**

- **`Category`** — plausibly `assetclass_l2` (a classification label present on all
  14 rows) or `asset_type` itself. Which one the reference means is unverified,
  and the two are different axes.
- **`Sub-Category`** — **no such field on a holdings row.** This is the same "Large
  Cap" vocabulary **B2** needs for its benchmark, from the same unverified place.
  `market_cap` is on the row and *might* serve for equity funds; do not assume it.
- **`Assets Management Company`** — **no AMC field.** `broker` is the source/broker
  code, not the AMC, and was an **empty string in 4 of 14 rows** (C2: never a safe
  grouping key). The AMC is inferable from the fund-name prefix ("Axis", "ICICI
  Pru") — but that is string inference on a field that is sometimes empty.
- **`Assets Under Management`** — **not in the holdings payload at all.** AUM is a
  *fund* attribute (`get_mf_funds_details` → `fund_detail.aum_history`;
  `get_mf_by_category` exposes it as a sort key). Note it describes **the fund's
  size, not the user's exposure**, so grouping by it answers a different question
  than the other four; and it is continuous, so it needs defined bands
  (small/mid/large AUM) that are a product decision, not a data one.
- **Plan badges (`GROWTH`, `REGULAR`/`DIRECT`)** — same problem. No field. Parseable
  from the fund name, and `REGULAR` vs `DIRECT` is a **real, expense-ratio-bearing
  claim about the user's money** — a badge inferred wrong is worse than no badge.

**The unblock is one enrichment call, and it needs a spike.**
`get_mf_funds_details(fund_ids, includes=[fund_detail, fund_performance,
category_tables])` is the plausible source of sub-category, AMC, AUM and plan for
every MF row at once (`fund_ids` is an array — one batched call, which matters at
15 calls/min per tool). **Unverified:** whether the row's `investment_code` *is* the
`fund_id` that tool accepts, and what it actually returns. Fold this into B2's
spike — it is the same tool and the same question.

**And there is a second, vendor-independent route: B4.** AMFI's daily NAV file
carries sub-category, AMC, plan and ISIN for all ~14k schemes, free and verified
live — enough to fill every blocked column above except AUM. It shifts the problem
from "does the vendor expose this" to "can we join a holdings row to a scheme",
which is the better problem to have. The two routes are complementary, not
alternatives: the spike is what decides whether the join key comes for free.

**Also settle:**

- **Drop the XIRR column.** C2 killed it and D1 already omits it deliberately:
  `xirr` was `0` in 14 of 14 rows and no dated cashflow exists anywhere in the API.
  The column comes back only when **B2** does. Do not ship an empty column as a
  promise.
- **The reference is an MF view; AlphaDesk's table is cross-asset.** NAV and Units
  are meaningless for `SA` and `FD`; `Category`/`Sub-Category`/`AMC`/`AUM` are MF
  concepts. Decide whether this is the MF-sleeve table or whether the column set
  and the group-by menu become **contextual per asset type** — the second is
  better and is the more expensive answer.
- **Grouping must show group subtotals honestly.** A group header summing its rows
  is an AlphaDesk-computed number and will not match a vendor bucket total; same
  rule as M1 §5, and unknown-basis rows must not silently count as `0` invested.
- Rows with `name is None` need a stable placeholder that still sorts, groups and
  searches — "unnamed" is a group, not a crash.
- Search should be client-side over the already-loaded rows; a search that fires
  MCP calls per keystroke walks straight into the rate limiter.

**Pick up when:** the columns/search/weight half can go any time. The group-by
half waits on the `get_mf_funds_details` spike shared with **B2**, and on **B4**
for whatever that spike does not supply. **B6** reuses this card's answers for its
own grouping — settle the cross-asset question once, here.

---

### B5 — Portfolio greeting header + Day's P&L

Reference design supplied 2026-08-17: a greeting line (`Good Afternoon, Ishan! 🎉`)
over a playful market-mood one-liner, a summary card carrying **Current Value**,
**Invested Amount**, **Total P&L** (abs + %) and **Day's P&L** (abs + %), and a
footer reading `Last updated a while ago · ⟳ Refresh Holdings`.

D1 already ships four stat cards, a live Refresh with a 30-second cooldown, and
the top bar. The delta is: the greeting, the mood line, the relative timestamp —
and **Day's P&L, which is the only hard part.**

**Day's P&L does not exist in the payload and cannot be read from it.** C2: no
date field at any level, and no previous-close or day-change field anywhere. Three
routes, and they are not equivalent:

1. **Diff against last night's S1 snapshot.** Available today with no new data.
   But a level difference **conflates market movement with money moving** — this is
   precisely B1's thesis. A ₹50k deposit renders as ₹50k of profit. Also `None` on
   the user's first day, and unattributable across a missing day or a bucket in
   `buckets_failed`. If used at all it must be labelled **"change since last
   snapshot"**, never "Day's P&L".
2. **Per-fund `units × ΔNAV` from B4's dated AMFI series.** Decomposes correctly,
   is immune to flow conflation while units are unchanged, and yields the *per-fund*
   number B6's treemap needs anyway. MF only. **This is the right route** — it makes
   Day's P&L a B4 dependency rather than a B1 one.
3. A vendor day-change field. There isn't one.

**MF NAVs publish once daily after close**, so before tonight's publish "today" is
genuinely **unknown, not zero** — the reference's own `0.00%` tiles are consistent
with "not yet published". Render `—`, the same way D1 already refuses to render an
unknown basis as `0.00%`.

**Settle these:**

- **"Last updated" must say *fetched*, not *as of*.** M1's `as_of` is stamped by
  the connector at fetch time because no payload carries a date. "Prices as of
  3:42pm" is a freshness claim we cannot make; "fetched 4 minutes ago" is true.
- **Greeting timezone: use IST.** S1's `attributed_day` already owns the IST rule,
  and a user abroad seeing "Good Morning" at their 2am is a smaller wrong than two
  parts of the app disagreeing about what day it is.
- **The name comes from Clerk and is often absent** — single-tenant local dev and
  flag-off have no name at all. The greeting must read well with no name rather
  than rendering "Good Afternoon, !".
- **Keep the mood line a static rotation keyed to observed direction, not an LLM
  call.** A1's overview is already spend-capped and currently paused
  (`OVERVIEW_DAILY_GLOBAL_MAX=0`); a per-pageload joke would be a new uncapped
  spend path and a new way for a page that must always render to fail. Whatever it
  says about the market has to key off a number we actually hold.
- **Do not port the loan cross-sell.** The reference's "Get cash up to ₹1,39,499
  against your MFs" is a credit-product referral — outside `V2_PLAN.md` §8.3's
  descriptive-only framing and a regulated-referral surface this project has not
  accepted. Deliberately excluded, not overlooked.

**Pick up when:** the greeting, mood line and relative timestamp can go any time.
Day's P&L waits on **B4** (preferred) or ships as a snapshot diff **only** with
B1's labelling honesty applied.

### B6 — P&L treemap (`Your Profit & Loss`)

Reference design supplied 2026-08-17: a treemap where **tile area = weight**,
**fill = signed return**, and each tile is labelled with the fund name and its
change %, over two controls — **Period** (`Total` | `Today`) and **Group by**
(`Funds` | `Category` | `Sub-Category`) — with an `Others` rollup tile for the
tail and truncated labels in tiles too small to hold one.

**What works today:** `Period = Total`, `Group by = Funds`. Area needs weight and
fill needs `pnl_pct`; both are in the M1 model already (see B3). That combination
could ship alone.

**What is blocked:** `Today` is B5's problem (and therefore B4's).
`Category` / `Sub-Category` is B3's problem (and therefore B4's / the
`get_mf_funds_details` spike's). The treemap has no independent blocker — it
inherits both.

**It conflicts with the locked design contract, and that needs settling first.**
`docs/design/DECISION.md` states: *"P&L: good `#059669` · bad `#dc2626` — status
colors never used as chart series colors."* A P&L treemap fills its marks with
exactly those colors. The spirit is arguably intact — the rule exists so **hue
never carries identity**, and here hue carries the *value* while identity stays in
the tile label, which is the same section's other rule — but the contract says it
literally. Amend `DECISION.md` explicitly before building this, rather than
shipping a silent exception to a document D1/U1 are bound by.

**Settle these:**

- **Say what the encoding is, in a legend.** "Your Profit & Loss" implies area = P&L,
  but area is *weight* and only the fill is P&L. A large holding with a small loss
  will look worse than a small holding that halved. That is a legitimate design
  choice and an illegible one if unlabelled.
- **The diverging scale needs a fixed midpoint at 0 and a clamp.** One outlier
  otherwise washes every other tile to the same shade.
- **Three states must be visually distinct: zero, unknown, and not-applicable.**
  `0.00%` (real, no move), `—` (NAV not published yet, or unknown cost basis where
  `invested_amount is None`), and cash-like rows that have no return *by nature* —
  C2 found `pnl_per == 0` on 3 of 3 `SA` rows for that reason. Rendering all three
  as a grey `0.00%` tile asserts three different falsehoods.
- **Red/green alone excludes colorblind readers.** The signed % is already in the
  label — keep it there, and prefer a luminance-differentiated ramp consistent with
  DECISION's ordered-ramp rule.
- **Define `Others`.** What falls in, how it is composed, and whether its own fill
  is a weighted average (a bucket mixing a +8% and a −8% holding into a neutral
  tile hides both). It needs a tooltip listing members.
- **Minimum tile size**, or the truncation in the reference (`Motial …`, `…`)
  becomes the common case rather than the tail.
- **Cross-asset again.** This is an MF-shaped mark; `SA`/`FD` do not belong in a
  return map. Decide whether it is the MF sleeve or the whole portfolio (B3 has the
  same open question — answer both the same way).

**Pick up when:** `Total` × `Funds` can go once DECISION.md is amended. The other
Period and Group by combinations arrive with **B4**/**B5**/**B3**.

---

## Tooling & process

### B7 — Evaluate Paper (`paper.design`) as the drafting surface for pending design work

**Researched 2026-08-17. Verdict: do not adopt as a source of truth yet; trial it
on exactly one card.** Recorded so it isn't re-researched, and so the re-evaluation
trigger is written down.

**Why it's even a candidate.** Our design contract is unusual: `docs/design/DECISION.md`
plus **four hand-written HTML/CSS reference pages**. Paper is an HTML/CSS-native
canvas — "designs export as code", real flexbox, real CSS properties, no
proprietary render layer — so unlike Figma its output is *the same medium our
contract is already written in*. It also ships an **MCP server**, meaning an agent
can read a design directly instead of squinting at a pasted screenshot, which is
precisely how B3/B5/B6 got specced in this session.

**Verified specifics:**

- **MCP server:** local HTTP at `http://127.0.0.1:29979/mcp`, started by the **Paper
  Desktop app** when a file is open. Claude Code install:
  `/plugin marketplace add paper-design/agent-plugins` then
  `/plugin install paper-desktop@paper`, or
  `claude mcp add paper --transport http http://127.0.0.1:29979/mcp --scope user`.
  **~24 tools, read *and* write:** page/selection/node inspection, screenshots,
  **JSX export**, computed styles; and create-artboard, parse/add HTML, set text,
  move/rename/duplicate/delete, update styles, plus `export` (PNG/JPG/SVG/MP4).
- **Pricing:** Free = unlimited viewers/editors but **100 MCP tool calls per week**;
  Pro = **$16/editor/mo billed yearly** ($20 monthly) for 1M calls/week; Orgs =
  custom (SAML/SSO).
- **Export targets:** React/JSX with Tailwind or inline styles, plus PNG/WebP/AVIF/MP4.

**The disqualifier is the roadmap, not the tool.** The three capabilities our stack
would actually depend on are **not shipped**:

- **Tailwind import/export ("idiomatic Tailwind")** — *In Progress*.
- **Themes and Tokens** — *In Progress*.
- **shadcn support** (under "Icon Packs & Component Kits", with Base UI) — *Planned*.

We are shadcn + Tailwind + zinc tokens. Adopting today means Paper emits HTML/CSS
that a human hand-translates back into shadcn primitives — **reintroducing exactly
the translation layer the tool exists to delete**, while adding a second place
where visual truth lives. `DECISION.md` + the reference pages are binding for D1
and U1; a rival source of truth is a worse problem than a slow design loop.

**Other things that would bite:**

- **The MCP is a local desktop dependency.** It only exists while the app has the
  file open, on one machine. It cannot be a CI, headless, or cron dependency, and
  any agent workflow built on it fails closed when the app is shut.
- **No auth on the endpoint** — a localhost HTTP server with *write* access to
  design files. Low risk on a personal machine; not something to expose.
- **Vendor-stated flakiness:** long sessions drop the connection (restart advised),
  and agents "can occasionally hallucinate the tools".
- **Free tier is ~one agent session** (100 calls/week). A real trial costs $16/mo.

**Recommended trial, if it happens:** **B6's treemap**, and nothing else. It is the
one pending design decision that is purely visual, self-contained, and already
blocked on a written question (the `DECISION.md` status-color amendment). Success
looks like: the treemap drafted on the canvas, exported, and **landed back as a
reference page + a DECISION.md amendment** — the contract stays where it is.
Failure looks like: the export needs enough hand-rework that it saved nothing.

**Re-evaluate when:** Tailwind integration and Themes/Tokens move from *In Progress*
to shipped, **and** shadcn support lands. At that point the argument changes
completely, because the export would land in our actual stack.

---

### Pending design decisions (need an answer before their cards can build)

Consolidated from B3/B5/B6 so they are visible in one place rather than buried in
prose. These are **decisions**, not tasks — each blocks a build.

| # | Decision | Card | Why it blocks |
| --- | --- | --- | --- |
| 1 | Amend `DECISION.md` to permit P&L status colors as treemap fill — or reject the treemap | B6 | The contract says "status colors never used as chart series colors"; building either way without amending it makes D1/U1's binding document untrue |
| 2 | Is the holdings surface the **MF sleeve** or the **whole portfolio**? | B3, B6 | Decides whether columns and group-by become contextual per asset type — the expensive answer, and both cards need the *same* answer |
| 3 | **Weight** = the vendor's `holding_percent` or `current_value / total`? And of the portfolio or of the visible group? | B3 | The two disagree by construction (M1 §5); a table showing both contradicts itself |
| 4 | How are **zero / unknown / not-applicable** distinguished visually? | B3, B6 | C2: cash-like rows are `0` *by nature*, unknown basis is `None`, unpublished NAV is neither. One grey tile for all three asserts three falsehoods |
| 5 | Diverging ramp + colorblind treatment; `Others` bucket definition; minimum tile size | B6 | Red/green alone excludes readers; an undefined `Others` hides its members |
| 6 | Day's P&L **wording and source** — `units × ΔNAV` (B4) vs a snapshot diff labelled "change since last snapshot" | B5 | A snapshot diff renders deposits as profit (B1); the label is the honesty |
| 7 | Greeting: IST vs browser-local; no-name fallback; static mood-line copy table | B5 | Cheap, but it is copy someone has to write |

Already filed on GitHub and still open: **#18** (Lab's look onto the product theme),
**#19** (analysis playground), both `needs-design`; **#20** tracks the post-polish
backlog round.

---

## Cut or heavily deferred

### "Worldmonitor" (macro / global market context, Indian lens)
A different product wearing the same login. It shares no data model with the
portfolio analyzer and would be a third unrelated page. Revisit only if it can
be expressed *through* the portfolio ("your portfolio's exposure to crude" is
portfolio analytics; "here is a world markets dashboard" is not).

### Portfolio-aware research ("what should I buy given my holdings")
Was listed as v2+ scope. Now blocked on product grounds, not effort: fusing
instrument-level recommendations with a real portfolio is the thing the
descriptive-only framing exists to avoid. The research desk stays a labelled
paper simulation.

### MF screener (`get_mf_by_category`), US stocks (`get_us_stocks_details`), liabilities/EMI, options analytics
Tools exist on the IND Money MCP; all out of scope. Keep the connector wrappers
extensible so they slot in without a refactor. Note **B2** would promote
`get_mf_by_category` (and `get_mf_funds_details(category_tables)`) from screener
nice-to-have into a dependency — it is where sub-category averages would come
from.

---

## Live order placement (broker execution)

**Status:** deferred — and not merely on effort. It conflicts with the product
framing settled on 2026-08-14.

What exists today: `backend/broker/base.py` defines `BrokerAdapter` (abstract
`place_order(action) -> OrderResult`) plus `load_broker()`, which reads the
`BROKER` env var and returns `None` because no concrete adapter ships. The
Execution agent (`backend/agents/execution.py:57`) already calls
`broker.place_order(...)` when an adapter is present and otherwise logs
"Broker integration not configured" and writes to the paper watchlist. So the
seam is built and dormant — nothing needs removing.

**Why it stays dormant.** The product is now a *descriptive* portfolio analyzer
with scenario projection, explicitly not instrument-level advice on real
holdings, and the research desk is a labelled simulation. Wiring real order
placement to the output of an LLM pipeline that emits `buy`/`avoid` with a
confidence score inverts every one of those decisions at once — and does it for
other people's money, on a public deployment.

**What would have to be true to revisit:** a deliberate reversal of the
descriptive-only framing with the regulatory position worked out first (SEBI
IA/RA), a real per-order human confirmation that is not the existing
`interrupt_before` graph gate, an audit trail, and a broker credential story
that does not involve storing order-capable secrets for strangers.

Keep the `BrokerAdapter` seam as-is. `BROKER` stays unset in every deployed
environment.

---

## Configurable model routing + NVIDIA NIM as a second provider

**Status:** deferred, but with a live trigger — on 2026-08-16 Groq decommissioned
`llama-3.3-70b-versatile`, which the Analyst and Risk Manager had **hardcoded**
(`ANALYST_MODEL`, `RISK_MODEL`). The swap to `openai/gpt-oss-120b` was a code
change and a redeploy, because there is no way to name a model from config. The
next such notice should be a `.env` edit, not a commit.

Two stages, in this order — the second is worthless without the first.

**Stage 1 — models configurable via `.env`.**
Every per-agent model constant (`SCANNER_MODEL`, `RESEARCH_MODEL`,
`ANALYST_MODEL`, `RISK_MODEL`, and the portfolio-overview models) becomes an env
override with the current value as its default, so an unset env keeps today's
behaviour exactly. Add NVIDIA NIM (`https://integrate.api.nvidia.com/v1`) as a
named provider in `get_chat_llm` — it is OpenAI-compatible, so it is closer to a
third `Provider` literal than to new transport code.

Design constraints, because this touches the one helper that A1 hardened:

- `provider=` must keep winning over the environment. The whole point of
  `agents/llm.py` is that a stray env var cannot reroute the portfolio agents
  off real OpenAI, and per-agent tiering in the Lab cannot silently collapse to
  one model. A config surface that re-opens that hole is a regression, not a
  feature — the existing `test_llm_routing.py` assertions are the contract.
- Prefer explicit per-agent vars (`ALPHADESK_ANALYST_MODEL=...`) over a single
  global override. One var that sets every agent's model *is* the collapsed
  tiering A1 spent effort preventing.
- The Analyst and Risk Manager both use `.with_structured_output`, and the
  Analyst's `confidence` feeds hard guardrail thresholds (0.70 REJECT / 0.75
  FLAG). Any model reachable from config must support structured output, and a
  swap needs a real pipeline run to check the confidence distribution — a green
  `pytest` proves nothing here, since no test exercises those two agents.
- Validate the model name at startup, not mid-pipeline: a typo in `.env` should
  fail the boot, not surface as a failed run three agents deep.

**Stage 2 — model switching in the frontend.**
Only after Stage 1 exists, and it needs its own plan. Open questions to settle
*before* building it: is the choice per-user (persisted where?) or per-run; is it
exposed for the Lab only, or for the portfolio overview too — where model choice
changes the cost and quality of *financial* output; and who absorbs the spend
when a user picks the expensive model. Related: **Bring-your-own LLM key** below,
which answers that last question by moving the bill to the user. If both ship,
they should ship as one coherent surface rather than two unrelated selectors.

**Pick up when:** the next model deprecation notice lands, or a second provider
is actually wanted for cost/latency reasons — whichever comes first.

---

## Small, cheap, not yet scheduled

### `segments` on `get_indian_stocks_details`
Verified against the live tool schema (`indmcp` v1.26.0): the signature is
`get_indian_stocks_details(ind_keys*:array, segments:?)` — the same optional
`segments` parameter its US counterpart has. The Research agent currently never
passes it, so analyst ratings and news sentiment are available and unused.
Cheap win for the Lab section whenever it gets attention. Not v2 scope.

### Bring-your-own LLM key
Let a user supply their own OpenAI (or compatible) API key in the frontend and
run the whole workflow on it, instead of the project's shared credits.

**Status:** deferred. Invite-only means a small, known user set, and project
credits cover it. Until then all users run on the project key; testing uses those
credits conservatively.

**Why it's wanted:** removes the project's LLM spend as a scaling ceiling and
removes the shared-quota abuse surface entirely — each user's usage is bounded by
their own billing.

**Design constraints when picked up (this is a credential feature, not a form
field):**
- Prefer **never persisting it server-side**: hold it in the browser session and
  send it per-request. If it must persist, it is Fernet-encrypted exactly like
  broker refresh tokens, never logged, never returned to the frontend.
- Either way the key **transits your backend**, so you can spend the user's
  money. That needs an explicit consent screen and a visible per-user usage
  readout, not a silent text input.
- Validate with one cheap call at entry so a bad key fails at setup, not
  mid-pipeline.
- Falling back to the project key when the user's key fails must be a deliberate,
  disclosed choice — never an invisible default.
- Privacy policy consequence: with a user's own key, prompts go to *their*
  provider account under *their* retention terms. The policy text differs between
  the two modes and must say which applies.

### Third-party error tracking
Sentry (or equivalent) on backend + frontend. Deferred in v2: with fewer than ten
waitlist-approved users you can ask them directly what broke, and structured
logging covers the rest.

**Why it isn't free to add:** Sentry captures request context, and this app's
requests carry financial data — it would need aggressive scrubbing (no request
bodies, no query params on portfolio routes) and would become a **third
subprocessor** named in the privacy policy alongside Groq and OpenAI.

**Pick up when:** user count outgrows "ask them directly", or before open sign-up.
