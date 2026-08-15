# IND Money portfolio payloads — C2 data spike

Card: **C2 — IND Money data spike**. Branch `spike/ind-money-portfolio` off
`main` @ `8caee5d`. Captured 2026-08-15 against the operator's linked account
via the live `indmcp` MCP server.

**Read the [go/no-go](#gono-go) at the bottom before starting M1.** That is the
human gate.

## Ground rules for this document

The repo is public. **No value from the operator's account appears anywhere in
this file, in the fixtures, or in any commit on this branch.** What is published
here is *schema*: tool names, parameter names, enum values, response field
names, JSON types, nesting, and **counts**. Evidence is phrased as
"field X was 0 in N of M rows", never as an amount, a fund, a ticker, a broker
name, or a date.

Raw captures lived only in a scratch directory outside the repo
(`…/scratchpad/c2-captures/`, 78 files) and were **deleted at the end of the
card**. See `docs/TESTING/C2.md` to re-run the capture.

---

## 1. Tool inventory actually found

`list_tools` on the authenticated session returns **15 tools**.

Server: `indmcp` **v1.26.0**, MCP protocol `2025-11-25`.

**Every tool declares the same `outputSchema`:**

```json
{"properties": {"result": {"title": "Result", "type": "string"}},
 "required": ["result"], "type": "object"}
```

That is, the MCP-level contract is a **single stringified-JSON blob** — the real
payload shape is undocumented at the protocol level and only knowable by
calling. `_unwrap` in `backend/tools/ind_money.py` already handles this. Every
shape in §2 below is the shape *after* unwrapping.

Note the drift between the declared `outputSchema` title and the tool name for
one tool: `networth_holdings` declares `networth_asset_holdingsOutput`. Harmless,
but it means the server has an internal name for that tool that is not the
exposed one.

### The four portfolio tools the plan guessed — all four exist, names exact

| Tool | Params (all `string` unless noted) | Notes |
| --- | --- | --- |
| `networth_snapshot` | *(none)* | Whole-portfolio aggregate. |
| `networth_holdings` | `asset_type`\* | Row-level holdings for one asset type. |
| `networth_allocation_breakdown` | `asset_type`\*, `breakdown_by`\* | One asset type, sliced. |
| `mf_sips` | *(none)* | Mutual-fund SIP schedule. |
| `indian_stocks_sips` | *(none)* | Indian-stock SIP schedule. |

\* = required.

**`asset_type` enum (16 values, identical on both tools that take it):**

```
IND_STOCK, MF, US_STOCK, BOND, EPF, NPS, SA, FD,
CRYPTO, INSURANCE, VEHICLE, RE, RD, AIF, PMS, PPF
```

This matches the plan's expected universe exactly. **No drift.**

**`breakdown_by` enum (3 values):** `assets`, `sector`, `market_cap` — also
exactly as the plan guessed.

> ⚠️ **Enum gap that matters (see Q3):** `networth_snapshot` reports a bucket
> under an `asset_type` value — `US_STOCK_WALLET` — that is **not in the
> `networth_holdings` / `networth_allocation_breakdown` enum**. There is no way
> to fetch line items for it.

### The other ten tools (market data / lookup — unchanged from v1 usage)

`get_indian_stocks_ohlc` (`ind_key`\*, `interval`\* ∈ 1minute/5minute/15minute/
30minute/60minute/240minute/1day/1week/1month, `lookback`\* ∈ 1d/7d/14d/1y) ·
`get_indian_stocks_details` (`ind_keys`\* array, `segments` ∈ analyst/news) ·
`get_indian_stocks_movers` (`category`\* ∈ top-gainers/top-losers/most-active/
52-week-high/52-week-low/upper-circuit-stocks/lower-circuit-stocks, `limit`
int=10) · `get_indian_stocks_option_chain` (`ind_key`\*, `use_expiry_date`\*
bool, `expiry_date`, `strikes_around_atm` int=7) ·
`get_indian_stocks_greeks_history` (`ind_key`\*, `lookback` ∈ 1d/7d) ·
`lookup_ind_keys` (`names`\* array, `filter_type` ∈ IN_STOCKS/IN_STOCKS_FNO/
US_STOCKS/MF) · `user_watchlist` (`type` ∈ indian/us/all) ·
`get_mf_funds_details` (`fund_ids`\*, `includes` ∈ fund_detail.aum_history/
fund_performance/asset_allocation/sector_allocation/holdings/category_tables) ·
`get_mf_by_category` (`categories`\* array, `size` int=6, `page` int=1,
`sort_key` ∈ category_ind_rank/returns_1yr/returns_3yr/returns_5yr/aum,
`sort_asc` bool=True) · `get_us_stocks_details` (`symbols`\* array, `segments`).

**There is no transaction-history, cashflow-ledger, or trade-book tool in the
inventory.** That single fact decides Q1.

---

## 2. Response shapes (post-unwrap)

### 2.1 `networth_snapshot()`

```
data
├─ total_networth          float   (2 dp)
├─ total_current_value     float   (2 dp)
├─ total_invested          float   (2 dp)
├─ liabilities             object
│  ├─ total                    float
│  ├─ total_loan_balance       float
│  ├─ total_credit_card_due    float
│  ├─ loans                    array   (empty in capture — element shape UNVERIFIED)
│  └─ credit_cards             array   (empty in capture — element shape UNVERIFIED)
├─ investments             array of object   ← keyed by asset_type
│  └─ { asset_type: str, invested_value: number, current_value: number,
│        return: number, return_percentage: number,
│        progress_value_percentage: float }
├─ assets                  array of object   ← keyed by assetclass_l2
│  └─ { assetclass_l2: str, invested_value: number, current_value: number,
│        return: number, return_percentage: number,
│        progress_value_percentage: float }
├─ sector                  array of object
│  └─ { sector: str, invested_value: float, current_value: float,
│        return: float, return_percentage: float,
│        progress_value_percentage: float }
└─ market_cap              array of object
   └─ { market_cap: str, invested_value: float, current_value: float,
        return: float, return_percentage: float,
        progress_value_percentage: float }
```

Row counts in the capture: `investments` 5, `assets` 4, `sector` 13,
`market_cap` 4, `liabilities.loans` 0, `liabilities.credit_cards` 0.

**Numeric-type warning for M1:** `invested_value`, `current_value`, `return` and
`return_percentage` come back as **`int` on some rows and `float` on others** —
JSON emits `5` not `5.0` when the value is integral. Any Pydantic model must use
`float` (or `Decimal` with a coercing validator), never `int`, and any test that
asserts on `type()` will be flaky across accounts.

**No `currency` field at any level. No `as_of` / date field at any level.**

### 2.2 `networth_holdings(asset_type=…)`

**Two structurally different payloads come back from the same tool**, depending
on asset type. This is the single biggest surprise of the spike.

**Shape A — the aggregator shape** (observed for `MF`, `SA`, `FD`, `US_STOCK`,
and for the 11 empty asset types):

```
data
└─ holdings   array of object
   └─ { asset_type:      str    (echoes the requested enum value)
        assetclass_l2:   str    (classification label)
        market_cap:      str    (classification label)
        sector:          — NOT present at row level (only in the breakdowns)
        investment:      str    (display name; empty string observed)
        investment_code: str    (vendor instrument id)
        broker:          str    (source/broker code; empty string observed)
        invested_amount: number
        market_value:    number
        total_units:     number
        unit_price:      number
        total_pnl:       number
        pnl_per:         number  (percent, simple)
        holding_percent: number  (share of portfolio, percent)
        xirr:            number  ← see Q1
      }
```

All 14 non-empty rows across all asset types share **exactly one key set** —
14 keys, no per-asset-type variation, no nulls, no extra fields. Empty asset
types return `{"holdings": []}` and nothing else (1 top-level key).

Same `int`-vs-`float` caveat as §2.1: e.g. `holding_percent` was `int` on the FD
and US_STOCK rows and `float` on the MF and SA rows; `invested_amount` was `int`
on some MF rows and `float` on others.

**Shape B — the live-trading envelope** (observed *only* for `IND_STOCK`):

```
data
├─ holdings                        array   (EMPTY in capture)
├─ positions                       null
├─ intra_day_positions             null
├─ mtf_positions                   null
├─ derivative_positions            null
├─ drv_intra_day_positions         null
├─ commodity_positions             null
├─ commodity_intra_day_positions   null
├─ strategy_positions              null
├─ open_orders                     array   (empty)
├─ open_derivative_orders          array   (empty)
├─ open_commodity_orders           null
├─ open_gtt_commodity_orders       null
├─ meta_info                       object  (empty)
├─ holding_error                   bool
├─ position_error                  bool
├─ is_cached_response              bool
├─ is_pledge_eligible              bool
└─ is_mtf_pledge_required          bool
```

19 top-level keys, none of them shared with Shape A beyond `holdings`.

> ⚠️ **`IND_STOCK` — the one asset type AlphaDesk exists for — returned zero
> holdings rows on this account.** The row shape inside Shape A's `holdings`
> array is therefore **completely unverified for Indian stocks**. It may match
> Shape A's row shape; it may be a broker-native row (which would explain the
> `holding_error` / `is_pledge_eligible` / MTF fields). We do not know, and no
> amount of re-reading these captures will tell us.

### 2.3 `networth_allocation_breakdown(asset_type=…, breakdown_by=…)`

```
data
├─ asset_type    str   (echoes the request)
├─ breakdown_by  str   (echoes the request)
└─ data          array of object
   ├─ breakdown_by=assets     → { assetclass_l2: str, … }
   ├─ breakdown_by=sector     → { sector: str, … }
   └─ breakdown_by=market_cap → { market_cap: str, … }
       where … = invested_value: float, current_value: float, return: float,
                 return_percentage: float, progress_value_percentage: float
```

The row bodies are identical to `networth_snapshot`'s `assets` / `sector` /
`market_cap` arrays; only the discriminator key changes. Empty combinations
return `{"asset_type": …, "breakdown_by": …, "data": []}`.

Coverage in the capture: 8 of 48 `asset_type × breakdown_by` combinations
returned rows; 40 returned an empty `data` list. Non-empty:
MF/assets(2), MF/sector(13), MF/market_cap(3), US_STOCK/assets(1),
US_STOCK/sector(1), US_STOCK/market_cap(1), SA/assets(1), FD/assets(1).
`IND_STOCK` returned 0 rows on all three breakdowns.

### 2.4 `mf_sips()` and `indian_stocks_sips()`

```
data └─ mf_sips             array   (EMPTY in capture)
data └─ indian_stocks_sips  array   (EMPTY in capture)
```

Both returned zero rows. **The SIP row shape is entirely unverified.** The tool
descriptions claim the rows carry SIP amount, frequency, status, next execution
date and a current-month installment breakdown — if true, these are the only
tools in the whole inventory that would carry **dates**. Unverified.

### 2.5 Fields the payloads do **not** have

Confirmed absent everywhere by a key-name walk over all 78 captured files:

- **No date/time field of any kind.** A scan for key names containing
  `date`, `cashflow`, `transaction`, `txn`, `installment`, `purchase`,
  `as_on`, `timestamp` matched **0 keys** across every capture.
- **No currency / fx / conversion field.** A case-insensitive scan for
  `currency`, `USD`, `INR`, `fx`, `exchange_rate`, `conversion` matched
  **0 of 78 files** — not as a key, not as a value.
- No per-row `sector` (sector only exists in the aggregate breakdowns).
- No quantity-lot / average-cost breakdown, no ISIN-labelled field.

---

## 3. The five questions

### Q1 — Is per-row XIRR in the payload?

**Answer: the field exists and is dead. XIRR is not obtainable from this MCP
server, either directly or by computing it.**

Evidence:

- `xirr` is a real key on every Shape-A holdings row — present in **14 of 14**
  non-empty rows, missing in 0.
- Its value was **exactly `0` in 14 of 14 rows** (MF 9/9, SA 3/3, US_STOCK 1/1,
  FD 1/1). There is not one non-zero `xirr` anywhere in the capture set.
- `IND_STOCK` returned **0 rows**, so XIRR could not even be tested on the asset
  type that matters most.
- The vendor's own tool description for `networth_holdings` advertises
  "P&L, P&L %, or XIRR for each holding" — so the field is *claimed* to be
  populated and simply is not, on this account.
- **XIRR cannot be computed client-side either.** It needs dated cashflows;
  the payloads carry **zero date fields** (§2.5), and the 15-tool inventory
  contains **no transaction-history or cashflow tool at all**. Both SIP tools —
  the only plausible source of dated installments — returned **0 rows**.

**Alternative return signal that IS present and non-zero:**

| Level | Field | Populated? |
| --- | --- | --- |
| Per holding row | `pnl_per` (simple return %) | non-zero in 11 of 14 rows; `0` in 3 of 14 (all 3 in one asset type where a simple-return figure is not meaningful) |
| Per holding row | `total_pnl` (absolute) | populated in 14 of 14 |
| Aggregate | `return`, `return_percentage` on `investments[]`/`assets[]`/`sector[]`/`market_cap[]` | populated in 26 of 26 snapshot rows |

These are **simple cumulative returns** (current vs invested), not
time-weighted or money-weighted. They are a legitimate substitute for a
"return" display and they must **not be labelled XIRR**.

Certainty caveat: one account, one session. This proves the field is
untrustworthy as shipped and that no client-side path to XIRR exists; it cannot
prove `xirr` is unconditionally `0` for every IND Money user forever.

### Q2 — How often is `invested_amount` missing or 0? Per source/broker.

**Answer: 0 of 14 in this capture — but the vendor documents the opposite, and
the capture cannot see the case the vendor warns about.**

Observed:

| asset_type | rows | `invested_amount` key missing | value `null` | value `0` | distinct `broker` values | rows with empty-string `broker` |
| --- | --- | --- | --- | --- | --- | --- |
| MF | 9 | 0 | 0 | 0 | 2 | 0 |
| SA | 3 | 0 | 0 | 0 | 1 | 3 |
| FD | 1 | 0 | 0 | 0 | 1 | 1 |
| US_STOCK | 1 | 0 | 0 | 0 | 1 | 0 |
| IND_STOCK | **0** | — | — | — | — | — |
| other 11 types | 0 | — | — | — | — | — |
| **total** | **14** | **0** | **0** | **0** | **3 non-empty across all types** | **4** |

Aggregate level, `invested_value`: **0 of 26** snapshot rows and **0 of 23**
allocation-breakdown rows were missing or zero.

**But the vendor's own `networth_holdings` tool description states, verbatim in
its schema text: for linked (non-INDmoney) brokers, `invested_amount` is often
missing and returned as `0`.** This account's holdings sit almost entirely on
IND Money's own rails — that is *why* the observed rate is 0/14. The zero rate
is a property of this account, not of the API.

Per-source conclusions M1 must not skip:

1. **`broker` is not a reliable grouping key.** It was an **empty string in 4 of
   14 rows** (all FD and all SA rows). Any dedup / source-attribution keyed on
   `broker` silently collapses those into one "unknown source" bucket.
2. Only **2 distinct non-empty broker values** were observed, both under MF — far
   too small a sample to state a per-broker missing rate.
3. `investment` (the display name) was an **empty string in 1 of 14 rows**, so
   even the human-readable label is not guaranteed.
4. Treat `invested_amount == 0` as **"unknown cost basis"**, not "invested
   nothing". Deriving `pnl = market_value - invested_amount` on such a row
   produces a fabricated 100% gain. M1 must model this as nullable and D1 must
   render it as "—", not as a number.

### Q3 — Does `networth_snapshot` return a usable total to store as `NUMERIC`?

**Answer: yes. `total_networth` is a single well-typed scalar, safe as
`NUMERIC(18,2)`. But do not build a reconciliation constraint against the
holdings rows — it will not balance, for a structural reason.**

- `data.total_networth` is a JSON float with **exactly 2 decimal places**, as
  are `total_current_value` and `total_invested`. `NUMERIC(18,2)` fits all three.
- Semantics confirmed exactly (difference **0.0**):
  `total_networth == total_current_value − liabilities.total`.
  So `total_networth` is **net** of liabilities; `total_current_value` is the
  gross portfolio value. Store whichever the product means, but store both —
  they are different numbers and both are needed.
- **Internally consistent:** `total_current_value` equals the sum of
  `investments[].current_value` (5 rows) and equals the sum of
  `assets[].current_value` (4 rows), in both cases to within floating-point
  noise (absolute difference well under 0.01 on a value many orders of
  magnitude larger).
- **NOT consistent with the holdings rows:** summing `market_value` over every
  `networth_holdings` call for all 16 enum values (14 rows total) lands about
  **2.3% below** `total_current_value` — far too large to be rounding.
  **Root cause identified:** `snapshot.investments[]` contains a bucket whose
  `asset_type` is `US_STOCK_WALLET`, and that value **is not in the
  `networth_holdings` `asset_type` enum** (verified against the tool's own input
  schema — 16 values, `US_STOCK_WALLET` absent). There is no call that can
  enumerate it. It is almost certainly uninvested wallet cash.

M1 implication: any `CHECK` or test asserting "sum of holdings == stored net
worth" is guaranteed to fail. Model the gap explicitly — either a synthetic
"unallocated / wallet cash" line item, or a documented tolerance.

### Q4 — Is any value non-INR? Is there a currency field?

**Answer: there is no currency field anywhere, and the question cannot be
resolved from this API surface. That is itself the finding.**

- Case-insensitive scan for `currency`, `USD`, `INR`, `fx`, `exchange_rate`,
  `conversion` across all 78 captured files: **0 hits** — no key, no value, no
  enum member. The declared `outputSchema` is `{"result": string}` for every
  tool, so there is no schema-level currency field to fall back on either.
- The **only** signal distinguishing a foreign-denominated row is the
  `asset_type` string itself (`US_STOCK`, and the unenumerable
  `US_STOCK_WALLET`). That is a label, not a currency tag.
- The single `US_STOCK` row carries `assetclass_l2` and `market_cap` labels but
  **no** `currency` / `fx_rate` / `original_currency` sibling to
  `invested_amount` / `market_value` / `unit_price`.
- `networth_snapshot` **already performs a flat, unlabelled cross-asset-type
  sum**: `total_invested` / `total_current_value` / `total_networth` add up
  buckets that include both Indian and US asset types, with no per-entry
  currency tag, no FX rate, and no "converted" flag.
- A magnitude comparison between the US_STOCK row and the INR-denominated rows
  is **inconclusive**: the gap is far larger than any plausible USD→INR factor,
  which points at a fractional/near-zero test position rather than at
  un-converted USD — but nothing in the payload confirms either reading.

**Risk of a naive sum:** AlphaDesk cannot verify whether IND Money pre-converts
`US_STOCK` / `US_STOCK_WALLET` to INR. If it does not, every cross-asset total,
every allocation percentage, and any guardrail arithmetic over
`invested_amount` / `market_value` is silently wrong, **with no field available
to detect or correct it after the fact**. The sole US_STOCK sample here is
near-zero, so the risk is unexercised, not disproven.

Mitigation for M1/D1: store `asset_type` on every row and gate cross-asset
aggregation behind an explicit allowlist. Either exclude `US_STOCK` /
`US_STOCK_WALLET` from headline INR totals or label the total as
"currency assumption unverified", until a live account with a meaningful US
position settles it.

### Q5 — Does DCR tolerate one client per user?

**Answer: mechanically yes — a second registration succeeded identically. But
the flow was never proven past `/register`, so F3 should ship one
pre-registered client.**

- Discovery (`/.well-known/oauth-authorization-server`) returned **200** and
  advertises a `registration_endpoint`.
- **Two** back-to-back registrations with distinct client names: attempt 1
  **201**, attempt 2 **201**. Both returned `client_id` and `client_secret`,
  with an **identical 9-key response shape** (`client_id`,
  `client_id_issued_at`, `client_name`, `client_secret`, `grant_types`,
  `redirect_uris`, `response_types`, `scope`, `token_endpoint_auth_method`).
  Not deduped, not rejected, not bound to the existing client.
- **No rate-limit signal:** `Retry-After`, `X-RateLimit-*` and `RateLimit-*`
  headers were absent on both responses (0 of 2).
- **DCR is fully unauthenticated** — the registration POST carried no token at
  all and still succeeded. By contrast, an unauthenticated `list_tools` **fails**
  (`ok: false`). So `/register` carries **no user identity whatsoever**; the
  account binding happens later, at `/authorize`.
- Discovery advertises `token_endpoint_auth_methods_supported =
  [client_secret_post, client_secret_basic]` — **no `none`** — so every
  DCR-minted client is a *confidential* client needing a stored secret.
  `grant_types_supported = [authorization_code, refresh_token]`,
  `response_types_supported = [code]`,
  `code_challenge_methods_supported = [S256]`. All consistent with the existing
  backend-mediated callback design.
- The existing token/client was **not** invalidated (no logout, no revocation
  call was made).

**Gaps.** Neither attempt exercised `/authorize` or `/token` with the newly
minted credentials, so there is no proof a DCR client can actually complete an
auth-code exchange. Two calls say nothing about behaviour at N-user volume, and
no `registration_access_token` was captured, so client lifecycle
(update/revoke/expiry) is unknown.

**F3 recommendation:** **one pre-registered confidential client**, reused for
every user's `/authorize` + `/token`, with per-user refresh tokens in the F1
`broker_links` table. Per-user DCR is not ruled out — it is unproven, and it
buys nothing, because `/register` carries no identity anyway.

---

## Go/no-go

**Verdict: GO for M1 — with three scope changes and one blocking unknown that
M1 must design around rather than assume away. The kill criterion is NOT
triggered.**

The kill criterion in the plan was: *if `networth_snapshot`/`networth_holdings`
return no usable per-holding values, D1/S1/A1 as specified are dead.* They do
return usable per-holding values — a stable 14-key row with invested amount,
market value, units, unit price, absolute and percentage P&L, and portfolio
weight, populated in 14 of 14 observed rows, plus a clean 2-decimal net-worth
total. D1, S1 and A1 survive.

**Scope changes, by card:**

- **A1 (AI overview) — CHANGED. Its XIRR metric is dead.** `xirr` was `0` in
  14 of 14 rows, there are no dated cashflows in any payload, and no tool in the
  inventory supplies them. Replace with `return_percentage` from
  `networth_snapshot` (simple cumulative return), and do not call it XIRR.
- **D1 (dashboard) — CHANGED, twice.** (a) Drop the holdings-table XIRR column
  or relabel it `Return %` sourced from per-row `pnl_per`. (b) Headline totals
  must not silently blend `US_STOCK`/`US_STOCK_WALLET` into an INR figure —
  exclude them or label the assumption (Q4).
- **M1 (model) — CHANGED, three ways.** (a) One holdings model does **not**
  fit: `IND_STOCK` returns a structurally different 19-key live-trading
  envelope, not the 14-key aggregator row. (b) All money/percent fields must be
  `float`/`Decimal`, never `int` — the API emits both for the same field.
  (c) `invested_amount == 0` means *unknown cost basis* (vendor-documented for
  linked brokers) and must be nullable in the model, never fed into a P&L
  calculation.
- **S1 (snapshots) — CHANGED, mildly.** There is **no `as_of` field in any
  payload**. S1's calendar-day attribution must stamp its own capture time at
  ingest; the vendor gives it nothing to anchor to. Also: do not add a
  reconciliation constraint between stored holdings and stored net worth — the
  unenumerable `US_STOCK_WALLET` bucket makes it ~2.3% off by construction.
- **F3 (per-user linking) — CONFIRMED, not changed.** Use one pre-registered
  OAuth client, per-user tokens (Q5).

**The one blocking unknown a human must weigh before M1 writes the
`IND_STOCK` model:** `IND_STOCK` — the entire point of AlphaDesk — returned **zero holdings
rows** on the operator's account, inside a payload envelope that shares almost
no keys with the other asset types. **We have never seen an `IND_STOCK`
holding row.** M1 can safely model `networth_snapshot` and the aggregator-shape
holdings today, but any `IND_STOCK` row model would be invention. Recommended
sequencing: build M1 against the verified shapes and the committed fixtures,
keep the `IND_STOCK` row model behind an explicitly-unverified boundary, and
re-run the capture against an account holding Indian stocks before D1 renders a
holdings table.

---

## Appendix — synthetic fixtures

`backend/tests/fixtures/ind_money/` holds hand-written, fully invented JSON
mirroring each shape above, including the edge cases this doc identifies
(missing `invested_amount`, `invested_amount: 0`, a zero-value holding, an empty
`broker`, an empty asset type, a single-holding portfolio, and a US_STOCK row
with no currency signal). Inventory and regeneration policy: that directory's
`README.md`. Leak-check procedure: `docs/TESTING/C2.md`.
