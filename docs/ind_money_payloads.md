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

Raw captures live only in a scratch directory outside the repo
(`…/scratchpad/c2-captures*/`) and never enter the working tree. They are
**retained until this card's verification and its human gate have both
passed** — a reviewer has to be able to re-derive every count below against
the evidence — and the orchestrator deletes them afterwards. See
`docs/TESTING/C2.md` to re-run the capture.

Counts here were re-derived against a same-day re-capture of the same account.
Shapes, key sets and row counts were stable; live prices had moved slightly
between the two fetches, which is visible in one place only (§3, Q3).

---

## 1. Tool inventory actually found

`list_tools` on the authenticated session returns **15 tools**.

Server: `indmcp` **v1.26.0**, MCP protocol `2025-11-25`.

**All 15 tools declare the same `outputSchema`**, differing only in its
`title`, which is generated per tool as `<tool_name>Output`:

```json
{"properties": {"result": {"title": "Result", "type": "string"}},
 "required": ["result"], "title": "<tool_name>Output", "type": "object"}
```

That is, the MCP-level contract is a **single stringified-JSON blob** — the real
payload shape is undocumented at the protocol level and only knowable by
calling. `_unwrap` in `backend/tools/ind_money.py` already handles this. Every
shape in §2 below is the shape *after* unwrapping.

That generator makes one tool's title disagree with its own name:
`networth_holdings` declares `networth_asset_holdingsOutput`. The other 14
titles match their tool names exactly. Harmless, but it means the server has an
internal name for that tool that is not the exposed one.

### The five portfolio tools the plan guessed — all five exist, names exact

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
> holdings rows on this account.** The row shape inside Shape B's `holdings`
> array is therefore **completely unverified for Indian stocks**. It may match
> Shape A's row shape; it may be a broker-native row (which would explain the
> `holding_error` / `is_pledge_eligible` / MTF fields). We do not know, and no
> amount of re-reading these captures will tell us.
>
> What the captures *do* settle (see Q3): `networth_snapshot` reports **no
> `IND_STOCK` bucket whatsoever**, so the empty response is the account holding
> no Indian stocks — not the endpoint failing or withholding them.

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

> ⚠️ **`data` is not guaranteed to be present at all.** An empty slice returns
> `data: []`, but a **throttled** call returns a completely different body with
> no `data` key (§2.5) — and this is the tool most likely to be throttled,
> since it is both the highest-volume call (48 in a full sweep) and the most
> expensive per call. `payload["data"]` is therefore unsafe; check for an
> `error` key first.

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

Both returned zero rows. **The SIP row shape is entirely unverified.**

The tool descriptions are the only evidence of what a populated row holds, and
they are worth reading closely, because these are the only two tools in the
whole inventory that promise a **date** at all. Verbatim from `list_tools`:

> Returns SIP data per fund, including fund name, category, SIP amount,
> frequency, next execution date, and status.

> Returns SIP data grouped per stock, including SIP amount, frequency,
> next execution date, status, and the current month's installment breakdown.

Every date these describe is **forward-looking or current-month**: the *next*
execution date, and the status of *this* month's installments (the surrounding
"Use when" bullets list "upcoming, in-progress, or failed SIP installments").
Neither description promises a dated history of past cashflows, and no other
tool supplies one — so even a fully populated SIP response would not yield the
cashflow series XIRR needs. That is why Q1's conclusion does not soften here.
Separately, SIPs cover only instruments bought on a schedule; a lumpsum
purchase would leave no trace in either tool even if both were populated.

### 2.5 Rate-limit errors arrive as a **normal, successful-looking response**

> ⚠️ **This is the single most likely way M1's ingest breaks in production, and
> nothing about it is visible in a happy-path capture.**

The server rate-limits on **two tiers** and reports a breach **in the response
body**, with MCP-level `isError: false`. There is no HTTP error, no exception,
and no header to check. The body replaces the expected payload entirely:

```
{ error:                "rate_limit_exceeded"
  message:              str           (prose, and it names which tier tripped)
  scope:                str           ∈ {"tool", "global"}
  window:               str           ∈ {"tool:min", "min"}  — pairs with scope
  tool:                 str           (the tool that tripped it)
  limit:                number        (calls allowed in this window)
  current:              number        (consumed before this call)
  cost:                 number        (what this call costs — not every call is 1)
  retry_after_seconds:  number }
```

**The two tiers, and which one you hit:**

| Tier | `scope` | `window` | Observed limit | Trips when |
| --- | --- | --- | --- | --- |
| Per-tool | `"tool"` | `"tool:min"` | 15/min | Hammering **one** tool — e.g. the 48-call breakdown sweep |
| Global | `"global"` | `"min"` | 30/min | A fast **mixed** sweep across tools |

The per-tool tier is the tighter one and trips **first** on any single-tool
burst, which is the shape of most ingest work. Do not code against one tier:
**read `scope`, `limit` and `retry_after_seconds` off the body** rather than
hard-coding either number, since a client that only understands the global tier
will misread a per-tool breach as a server-wide outage and back off far more
than it needs to.

Consequences M1 must handle:

1. **`isError` is not a success signal.** A throttled call is `isError: false`.
   The only reliable check is *"does the unwrapped body contain an `error`
   key?"* — test that **before** touching the payload.
2. **`payload["data"]` / `payload["holdings"]` will `KeyError`.** The documented
   shapes in §2.1–§2.4 are simply absent on a throttled call. Any parser that
   indexes straight into them crashes rather than degrading.
3. **Calls are not equally priced.** `networth_allocation_breakdown` costs
   **2**, so the 48-call breakdown sweep spends 96 units, not 48 — and against
   a 15/min per-tool budget it trips after **7 calls**. Budget by **cost**, not
   by number of calls.
4. **`retry_after_seconds` is the backoff to honour.** It is the only
   quantitative recovery signal the server gives.
5. **`current` is the count *before* this call.** In the captured breach
   `current + cost` exceeds `limit` while `current` alone does not — the server
   rejects a call whose cost would take it over, rather than waiting for the
   counter itself to reach the limit. A client that compares only `current` to
   `limit` will conclude it had budget left.

**Evidence basis — verified.** This envelope was captured directly: a
deliberate read-only burst against one tool tripped the limit on **call 8** and
the raw response was saved (`rate_limit_envelope.json`). The **9 keys**,
`isError: false`, the body-replaces-payload behaviour, `cost: 2` for
`networth_allocation_breakdown`, and the per-tool `scope`/`window` pair are all
confirmed against that capture.

Two caveats. The **global tier** (30/min, `scope: "global"`, `window: "min"`)
comes from the run-1 notes of a fast mixed sweep and has **no preserved
capture** — the tier exists, but treat that number as one observation. And the
specific limits are server configuration, not a contract: read them off the
body.

### 2.6 Fields the payloads do **not** have

Confirmed absent everywhere by a key-name walk over all **67 payload captures**
(1 snapshot + 16 holdings + 48 breakdowns + 2 SIP), which between them use
**54 distinct key names**:

- **No date/time field of any kind.** A scan for key names containing
  `date`, `cashflow`, `transaction`, `txn`, `installment`, `purchase`,
  `as_on`, `timestamp` matched **0 of those 54 keys**.
- **No currency / fx / conversion field.** A case-insensitive scan for
  `currency`, `USD`, `INR`, `fx`, `exchange_rate`, `conversion` matched
  **0 of the 67 payload files** — not as a key, not as a value.
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
- The vendor's own `networth_holdings` description advertises it. Verbatim
  from `list_tools`, one of that tool's "Use for" bullets reads:

  > - P&L, P&L %, or XIRR for each holding

  So the field is *claimed* to be populated and simply is not, on this account.
- **XIRR cannot be computed client-side either.** It needs dated cashflows;
  the payloads carry **zero date fields** (§2.6), and the 15-tool inventory
  contains **no transaction-history or cashflow tool at all**. Both SIP tools
  returned **0 rows** — and, per §2.4, their own descriptions promise only the
  *next* execution date and the *current* month's installments, so even
  populated they would carry a forward-looking schedule, not the past-dated
  cashflow series XIRR requires.

**Alternative return signal that IS present and non-zero:**

**"Populated" means non-null, not non-zero — and the difference matters**, because
these are the exact fields A1 and D1 are being told to display *instead of* XIRR.

| Level | Field | Present & non-null | Non-zero |
| --- | --- | --- | --- |
| Per holding row | `pnl_per` (simple return %) | 14 of 14 | **11 of 14**; `0` in 3 |
| Per holding row | `total_pnl` (absolute) | 14 of 14 | **11 of 14**; `0` in 3 |
| Aggregate | `return`, `return_percentage` on `investments[]`/`assets[]`/`sector[]`/`market_cap[]` | 26 of 26 snapshot rows | **24 of 26**; `0` in 2 |

The zeros are not noise, and they are not a coincidence — **they are the
cash-like buckets, and they line up exactly:**

- The 3 zero `total_pnl` / `pnl_per` rows are **the same 3 rows**, all `SA`.
- The 2 zero aggregate `return` / `return_percentage` rows are the **`SA` and
  `US_STOCK_WALLET`** buckets in `investments[]` — and on both,
  `invested_value == current_value` exactly. No row in `assets[]`, `sector[]`
  or `market_cap[]` is zero.

So a `0` here means **"this holding has no return by nature"**, not "it broke
even after gains and losses". D1 must not render it as a computed `0.00%`
performance figure alongside genuinely-performing rows, and A1 must not average
it into a headline return. Treat cash-like rows as *not applicable*, the same
way §3 Q2 says to treat `invested_amount == 0` as unknown cost basis rather
than zero.

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

| asset_type | rows | `invested_amount` key missing | value `null` | value `0` | distinct **non-empty** `broker` values | rows with empty-string `broker` |
| --- | --- | --- | --- | --- | --- | --- |
| MF | 9 | 0 | 0 | 0 | 2 | 0 |
| SA | 3 | 0 | 0 | 0 | **0** | 3 |
| FD | 1 | 0 | 0 | 0 | **0** | 1 |
| US_STOCK | 1 | 0 | 0 | 0 | 1 | 0 |
| IND_STOCK | **0** | — | — | — | — | — |
| other 11 types | 0 | — | — | — | — | — |
| **total** | **14** | **0** | **0** | **0** | **3 distinct, none shared across types** | **4** |

Aggregate level, `invested_value`: **0 of 26** snapshot rows and **0 of 23**
allocation-breakdown rows were missing or zero.

**But the vendor documents the failure mode in the tool's own description.**
Verbatim from `list_tools`:

> For linked (non-INDmoney) brokers, invested_amount is often missing and
> returned as 0.

This account's holdings sit almost entirely on IND Money's own rails — that is
*why* the observed rate is 0/14. The zero rate is a property of this account,
not of the API.

Per-source conclusions M1 must not skip:

1. **`broker` is not a reliable grouping key.** It was an **empty string in 4 of
   14 rows** (all FD and all SA rows). Any dedup / source-attribution keyed on
   `broker` silently collapses those into one "unknown source" bucket.
2. Only **3 distinct non-empty `broker` values** were observed across the whole
   portfolio — 2 under MF, 1 under US_STOCK, none shared between asset types,
   and none at all on the SA and FD rows. Far too small a sample to state a
   per-broker missing rate.
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
  **2.34% below** `total_current_value` — far too large to be rounding.

**Principal cause, re-derived bucket by bucket against the captures.** The
unenumerable bucket is the *principal* cause but **not the whole story**, and
the doc previously claimed a single root cause without doing the arithmetic:

- `snapshot.investments[]` contains a bucket whose `asset_type` is
  `US_STOCK_WALLET`, and that value **is not in the `networth_holdings`
  `asset_type` enum** (verified against the tool's own input schema — 16 values,
  `US_STOCK_WALLET` absent). No call can enumerate it. It is almost certainly
  uninvested wallet cash. Its `current_value` is **2.348% of
  `total_current_value`** against a **2.339%** gap — so the wallet does not
  merely fail to explain the gap exactly, it **over-explains** it by 0.4% of its
  own size. Subtracting it leaves a residual of **−0.0088%** of the portfolio
  total, with the sign pointing the other way.
- That residual is not rounding. **Per-type buckets do not equal their own
  holdings sums either**, and relative to each bucket the discrepancies are far
  larger than the portfolio-level figure makes them look:

  | bucket | rows | (holdings sum − bucket) / bucket |
  | --- | --- | --- |
  | `SA` | 3 | `0.000%` — exact to the paisa |
  | `FD` | 1 | `0.000%` — exact to the paisa |
  | `MF` | 9 | **+0.015%** |
  | `US_STOCK` | 1 | **+0.944%** |

- Every **market-priced** (`MF`, `US_STOCK`) row's `market_value` equals
  `total_units × unit_price` to the paisa — 10 of 14 rows — so those **rows are
  internally consistent** and it is the aggregate that disagrees with them. The
  other 4 rows (3 `SA`, 1 `FD`) carry `total_units` **and** `unit_price` of
  exactly `0` alongside a non-zero `market_value`: cash-like holdings get no
  unit/price decomposition at all, so the identity is not merely violated
  there, it is undefined. **M1 must never derive value as `units × price`** —
  it silently yields `0` for every FD and savings row.
- With **no `as_of` field anywhere** (§2.6) nothing in the payload can confirm
  why the aggregate disagrees, but the likeliest reading is that the snapshot
  and the holdings rows are priced from different refreshes — which fits the
  pattern exactly: the two market-priced types (`MF`, `US_STOCK`) drift while
  the two cash-like ones (`SA`, `FD`) reconcile to the paisa, and the
  thinly-held `US_STOCK` bucket drifts most in relative terms.

**The decisive fact about `IND_STOCK`, which the doc should have stated
outright:** `snapshot.investments[]` has **no `IND_STOCK` bucket at all** — not
a zero-valued one, not a hidden one. The five buckets present are MF, SA,
US_STOCK_WALLET, FD and US_STOCK. So `networth_holdings(IND_STOCK)` returning
zero rows is **consistent with the account simply holding no Indian stocks**,
and is *not* evidence of a broken, permission-limited or differently-shaped
endpoint. That narrows the §2.2 warning: the 19-key envelope is real and its
row shape is still unverified, but there is no sign of a suppressed or
unreadable Indian-stock position hiding behind it.

**M1 implication, and it is stronger than "add the wallet back".** Any `CHECK`
or test asserting `sum(holdings) == stored net worth` is guaranteed to fail, by
~2.3% from the unenumerable wallet bucket alone. But **do not "fix" it by
asserting `sum(holdings) + wallet == total` either** — that check fails too, on
this very capture, because the per-type sums do not equal their own buckets.
There is no arrangement of these fields that balances exactly.

Model the gap explicitly: a synthetic "unallocated / wallet cash" line item for
the unenumerable bucket, **plus a documented tolerance** for the residual. A
tolerance of ~1% of any single asset-type bucket would have accommodated
everything observed here; anything tighter than that is betting on two
independently-refreshed price sets agreeing, which they demonstrably do not.

### Q4 — Is any value non-INR? Is there a currency field?

**Answer: there is no currency field anywhere, and the question cannot be
resolved from this API surface. That is itself the finding.**

- Case-insensitive scan for `currency`, `USD`, `INR`, `fx`, `exchange_rate`,
  `conversion` across all 67 payload captures: **0 hits** — no key, no value, no
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

**Answer: yes — per-user/per-login DCR is VIABLE, so F3's plan default (per-user
DCR, client id/secret stored on the link row, reused on re-link) STANDS
UNCHANGED.** Repeat registration is not merely tolerated, it is what the app
already does on every single login, and those clients complete the full
auth-code exchange in production. The first write-up of this section recommended
a pre-registered client instead; that was wrong, and it is corrected below.

> **Evidence basis — read this before relying on the bullets below.** The raw
> DCR probe capture was lost with the original capture set, and it was
> **deliberately not re-run**: every probe registration mints a real OAuth
> client on the vendor's server, and repeating a side-effecting call to
> re-create a file is not a trade worth making. So the probe bullets are
> reproduced **as recorded in the run-1 notes**, not re-derived from a capture
> on disk, and they are marked accordingly. The corroborating evidence below
> them is independently checkable in this repo and in normal operation, and it
> is what actually carries the conclusion.
>
> One asymmetry worth knowing: the **discovery document is a plain
> unauthenticated `GET` with no side effect**, so anything sourced from it
> (including the two fields F3 depends on, below) *can* be re-verified freely at
> any time. It is only `POST /register` that must not be casually repeated.

**From the run-1 probe, as recorded (not re-verifiable from captures):**

- Discovery (`/.well-known/oauth-authorization-server`) returned **200** and
  advertises a `registration_endpoint`.
- **Two** back-to-back unauthenticated `POST /register` calls with distinct
  fresh client names: attempt 1 **201**, attempt 2 **201**. Both returned an
  **independent** `client_id` + `client_secret` pair, with an **identical
  9-key response shape** (`client_id`, `client_id_issued_at`, `client_name`,
  `client_secret`, `grant_types`, `redirect_uris`, `response_types`, `scope`,
  `token_endpoint_auth_method`). Not deduped, not rejected, not bound to the
  existing client.
- The granted `scope` came back as **`portfolio:read` only** — read-only, and
  the same scope the app requests (`_SCOPE` in `tools/ind_money_auth.py`,
  overridable via `IND_MONEY_OAUTH_SCOPE`).
- **No rate-limit *headers*:** `Retry-After`, `X-RateLimit-*` and `RateLimit-*`
  were absent on both responses (0 of 2). **Do not read that as "no rate
  limit."** §2.5 shows this vendor signals throttling **in the response body**,
  not in headers — so on this server, absent headers are the expected case
  whether or not a limit exists. This bullet says nothing either way.
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
- **Two discovery fields F3 depends on**, both easy to miss:
  - `revocation_endpoint`, with `revocation_endpoint_auth_methods_supported`.
    So **F3 can revoke a user's tokens on unlink** rather than just forgetting
    them locally — which is the difference between "we deleted our copy" and
    "the grant is dead". Note the scope of that carefully: RFC 7009 revocation
    kills **tokens**, not client *registrations* (see the gaps below).
  - `scopes_supported = [portfolio:read, market:read]` — the whole scope
    universe is **two read scopes**. There is no write scope to accidentally
    request, which is worth stating plainly in a repo whose headline promise is
    that no order is ever placed. The app requests `portfolio:read`.
- The existing token/client was **not** invalidated (no logout, no revocation
  call was made).

**Corroborating operational fact — this is the load-bearing evidence.**
Checkable in this repo, no probe required:

- **AlphaDesk already performs DCR on every login.**
  `tools/ind_money_auth.begin_login()` calls `_register_client()`
  unconditionally, with the comment *"Always register a client bound to our
  redirect_uri (don't reuse a cached client registered for a different
  redirect)"*. There is no cache, no reuse branch, no pre-registered-client
  path in the code at all.
- **It has been doing so in production, repeatedly.** Two distinct clients were
  minted minutes apart during the 2026-08-15 re-authentication. Note the app
  sends a **constant** `client_name` (`"AlphaDesk"`), not a fresh random one —
  so the server does not dedupe on client name either, which is a stronger
  result than the probe's distinct-names test.
- **Those clients complete the full exchange.** This is what closes the gap the
  probe left open: a DCR-minted client is carried through `/authorize` with
  PKCE (`S256`) and then through `/token`, and the resulting refresh token
  drives the hourly access-token refresh that produced every capture in this
  document. Per-login DCR is not a hypothesis; it is the only auth path this
  codebase has ever used.
- `_register_client` also **does not disturb the live token chain** — the new
  client is adopted only once login completes, so an in-flight refresh is not
  broken by a concurrent re-link.

**Remaining gaps.** Two probe calls plus routine app usage say nothing about
behaviour at **N-user volume**, and the absent rate-limit headers are no comfort
at all now that §2.5 shows this server throttles **in the body** — a
registration limit could exist and would look exactly like this until it fired.
Separately, `revocation_endpoint` covers **tokens, not client registrations**:
no `registration_access_token` was captured, so RFC 7592 client lifecycle
(update / delete / expiry) remains unknown and **DCR clients accumulate
server-side with no cleanup path we know of**. One client per login makes that
accumulation linear in logins, not in users.

**F3 recommendation — the plan's default STANDS; the original write-up inverted
it.** The plan's default was per-user DCR: register per user, store
`client_id` / `client_secret` on the link row, reuse on re-link. The first
write-up replaced that with "one pre-registered client" — but the fallback it
was invoking is conditioned on *C2 finding per-user DCR unviable*, and **that
trigger never fired**. Per-user/per-login DCR is viable on both the probe
evidence and operational proof: every real login completes `/authorize` +
`/token` with a freshly DCR'd client, including two distinct clients minted
during the 2026-08-15 re-auth.

So:

- **Keep the plan default.** F3 stores `client_id` / `client_secret` on the
  `broker_links` row beside the per-user refresh token and reuses them on
  re-link. That is *less* registration churn than today's code, which mints a
  fresh client on every login — a refinement of the current behaviour, not a
  change of approach.
- **Adopting a pre-registered client would change shipped code**, since
  `begin_login()` registers per login today, and would swap a path proven
  end-to-end for one never exercised against this server. That is the more
  dangerous direction, not the safer one.
- **One pre-registered confidential client stays documented as the fallback**,
  to be adopted only if a restriction actually appears — a registration rate
  limit, a per-account client cap, or DCR being withdrawn. Watch registration
  volume for exactly that.

---

## Go/no-go

**Verdict: GO for M1 — with scope changes to four downstream cards (A1, D1, M1,
S1), F3's plan default confirmed, and one blocking unknown that M1 must design
around rather than assume away. The kill criterion is NOT triggered.**

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
  `networth_snapshot` (simple cumulative return), and do not call it XIRR. Note
  the substitute is itself `0` on 2 of 26 aggregate rows — the cash-like `SA`
  and `US_STOCK_WALLET` buckets, where `invested_value == current_value`. Those
  are "no return by nature", not zero performance; do not average them into a
  headline figure (Q1).
- **D1 (dashboard) — CHANGED, twice.** (a) Drop the holdings-table XIRR column
  or relabel it `Return %` sourced from per-row `pnl_per` — which is `0` on 3 of
  14 rows (all `SA`, cash-like), so render those as "—", not `0.00%` (Q1).
  (b) Headline totals must not silently blend `US_STOCK`/`US_STOCK_WALLET` into
  an INR figure — exclude them or label the assumption (Q4).
- **M1 (model) — CHANGED, three ways.** (a) One holdings model does **not**
  fit: `IND_STOCK` returns a structurally different 19-key live-trading
  envelope, not the 14-key aggregator row. (b) All money/percent fields must be
  `float`/`Decimal`, never `int` — the API emits both for the same field.
  (c) `invested_amount == 0` means *unknown cost basis* (vendor-documented for
  linked brokers) and must be nullable in the model, never fed into a P&L
  calculation. (d) **Rate-limit errors arrive as a normal response with
  `isError: false`** and an `error` body that replaces the payload entirely
  (§2.5) — ingest must check for an `error` key *before* indexing into `data` /
  `holdings`, or a throttled call becomes a `KeyError` instead of a retry.
  Budget by the per-call `cost`, not by call count, and honour
  `retry_after_seconds`.
- **S1 (snapshots) — CHANGED, mildly.** There is **no `as_of` field in any
  payload**. S1's calendar-day attribution must stamp its own capture time at
  ingest; the vendor gives it nothing to anchor to. Also: do not add a
  reconciliation constraint between stored holdings and stored net worth — the
  unenumerable `US_STOCK_WALLET` bucket makes it ~2.3% off by construction, and
  **adding the wallet back does not fix it**: per-type sums miss their own
  buckets by up to `0.944%` (Q3), so no exact equality holds. Use a documented
  tolerance.
- **F3 (per-user linking) — plan default CONFIRMED. The first write-up of
  Q5 inverted it and is corrected.** Per-user DCR is **viable**, so F3 keeps the
  plan's default: register per user, store `client_id`/`client_secret` on the
  link row, reuse on re-link. The "one pre-registered client" fallback is
  conditioned on C2 finding per-user DCR unviable — that trigger never fired,
  and adopting it would *change shipped code*, since `begin_login()` registers
  per login today and completes `/authorize` + `/token` in production. The
  fallback stays documented for the day a restriction appears. Open risk is
  volume, not viability: registrations accumulate with no known client-deletion
  path, and this server signals limits in response bodies (§2.5), so the absent
  rate-limit headers prove nothing.

**The one blocking unknown a human must weigh before M1 writes the
`IND_STOCK` model:** `IND_STOCK` — the entire point of AlphaDesk — returned **zero holdings
rows** on the operator's account, inside a payload envelope that shares almost
no keys with the other asset types. **We have never seen an `IND_STOCK`
holding row.** The snapshot confirms *why* — the account carries no `IND_STOCK`
bucket at all (Q3), so this is an empty portfolio slice rather than a broken
endpoint — but that does not make the row shape any less unknown. M1 can safely
model `networth_snapshot` and the aggregator-shape holdings today, but any
`IND_STOCK` row model would be invention. Recommended
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
