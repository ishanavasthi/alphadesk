# Demo portfolio — 100% invented

Every value in this directory was made up for card M1. **Nothing here is
derived from any real account, any capture, or any IND Money payload.** No
ticker, fund, ISIN, amount, unit count, price or date corresponds to anything
that exists. Names are prefixed `Demo ` and identifiers `DEMO`/`INE000DEMO*` so
a value from here can never be mistaken for a real one.

These files back `portfolio.connectors.stub.StubConnector`, which is **product
code, not test scaffolding**: it is the second real implementation of the
connector interface, it backs the public `/demo` route (card U1), and it is what
makes F4's cross-user isolation testable in CI forever.

## Shape

The files use the **model's own vocabulary** (`portfolio.models` field names),
not any vendor's. That is deliberate: if the stub parsed a vendor shape it would
be a second IND Money connector wearing a disguise, and the interface would
never actually get exercised by two different sources.

| File | Contents |
| --- | --- |
| `snapshot.json` | Portfolio totals plus the four aggregate breakdowns. |
| `holdings.json` | Object keyed by **raw asset-type string** → array of rows. |
| `allocations.json` | Object keyed `"<ASSET_TYPE>\|<breakdown_by>"` → array of slices. A missing key means "no rows for that combination", which is what the real source returns for most of the grid. |
| `sips.json` | `{"mf": [...], "ind_stock": [...]}`. |

Derived numbers (`pnl`, `pnl_pct`, `avg_cost`) are **not** stored — the stub
computes them through the same `derive_pnl` the model exposes, so the degrade
rules are exercised rather than pre-baked.

## The edge cases this portfolio deliberately contains

Each one mirrors a finding in `docs/ind_money_payloads.md`. Removing any of them
silently weakens the contract tests.

1. **Unknown cost basis** — `MF` row `DEMO-MF-0002` has `invested_amount: 0`,
   and `SA` row `DEMO-SA-0001` omits the key entirely. Both must yield
   `invested_amount = None` and **`pnl`/`pnl_pct` of `None`** — never a
   fabricated 100% gain.
2. **Zero-value holding** — `MF` row `DEMO-MF-0003` has `current_value: 0` with
   a real cost basis, so its P&L is a genuine −100%. Guards the divide-by-zero
   path in percentage math.
3. **An UNKNOWN asset type** — the `US_STOCK_WALLET` bucket is not one of the 16
   enum values. It must map to `AssetType.UNKNOWN` with the original string kept
   in `asset_type_raw`, and it must still count toward the totals it belongs to.
4. **A cash-like row with no unit/price decomposition** — the `FD` and `SA` rows
   carry `null` units and price beside a real value. Value must never be derived
   as units × price.
5. **A no-return-by-nature row** — the wallet holding and the snapshot's `SA`
   bucket have `invested_amount == current_value`, so a `0` return there means
   "this holding has no return", not "it broke even".
6. **A snapshot bucket with no holdings rows** — `EPF` appears in
   `snapshot.json` with a real value and has **no entry in `holdings.json`**.
   This reproduces the un-enumerable bucket the real source has, so the sum of
   holdings deliberately does **not** equal the snapshot total. Nothing may
   assert that it does.
7. **Mixed `int` and `float`** for the same field across rows, because JSON
   emits `5` where the value is integral and any model that pins a type breaks
   on the next account.
