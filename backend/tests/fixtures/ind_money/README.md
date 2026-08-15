# IND Money MCP fixtures — 100% synthetic

**Every value in this directory is invented.** No ticker, fund, scheme, amount,
unit count, price, date, account id, client id or broker identifier here came
from a real account. What is real is only the **schema**: key names, JSON types,
nesting, array-vs-object, and the `asset_type` / `breakdown_by` enum values
(which come from the server's public *input* schema, not from anyone's data).

Every invented string is prefixed `Fixture ` or `FIX` so it is impossible to
mistake a fixture value for a real one at a glance.

These fixtures were hand-written for card **C2** from the shape documentation in
[`docs/ind_money_payloads.md`](../../../../docs/ind_money_payloads.md). Read that
doc before using them — it explains *why* each edge case below exists.

## What layer these mirror

All files except `raw_mcp_envelope__*.json` mirror the payload **after
unwrapping**, i.e. what `_unwrap()` in `backend/tools/ind_money.py` returns.
The MCP wire format for every tool on this server is
`{"result": "<stringified JSON>"}`; `raw_mcp_envelope__networth_snapshot.json`
is the one fixture that keeps that outer wrapper, so the unwrap path itself can
be tested.

## Inventory

| File | Mirrors | Why it exists |
| --- | --- | --- |
| `networth_snapshot.json` | `networth_snapshot()` | Full shape. `investments` / `assets` / `sector` / `market_cap` / `liabilities`. Totals reconcile: `total_current_value` == sum of `investments[].current_value` == sum of `assets[].current_value`, and `total_networth` == `total_current_value − liabilities.total`. Contains a `US_STOCK_WALLET` bucket (an `asset_type` the holdings tool's enum does **not** accept) and mixes `int` and `float` for the same fields on purpose. |
| `networth_snapshot__single_holding.json` | `networth_snapshot()` | Single-holding portfolio: one row in every array, no liabilities. |
| `networth_snapshot__empty.json` | `networth_snapshot()` | Zero-value portfolio: all totals `0.0`, all arrays empty. |
| `networth_holdings__MF.json` | `networth_holdings(asset_type="MF")` | The edge-case workhorse — 6 rows, see below. |
| `networth_holdings__US_STOCK.json` | `networth_holdings(asset_type="US_STOCK")` | Foreign-denominated row. **Carries no currency field**, because the real payload carries none — the only signal is `asset_type`. |
| `networth_holdings__single_holding.json` | `networth_holdings(...)` | Single-row holdings response. |
| `networth_holdings__empty_asset_type.json` | `networth_holdings(...)` | The exact response for an asset type the account holds nothing in: `{"holdings": []}`, one key, nothing else. |
| `networth_holdings__IND_STOCK__empty.json` | `networth_holdings(asset_type="IND_STOCK")` | **Different envelope.** `IND_STOCK` returns a 19-key live-trading payload (positions, orders, pledge/MTF flags), not the 14-key aggregator shape. This mirrors the observed, empty one exactly. |
| `networth_holdings__IND_STOCK__populated.UNVERIFIED.json` | *guess* | ⚠️ **Not verified against reality.** The operator's account held zero `IND_STOCK` rows, so **no one has ever seen a populated `IND_STOCK` holdings row.** This file assumes the rows look like the aggregator shape. Do not treat a passing test against it as proof the model is right. |
| `networth_allocation_breakdown__MF__assets.json` | `…(asset_type="MF", breakdown_by="assets")` | Discriminator key is `assetclass_l2`. |
| `networth_allocation_breakdown__MF__sector.json` | `…(breakdown_by="sector")` | Discriminator key is `sector`. |
| `networth_allocation_breakdown__MF__market_cap.json` | `…(breakdown_by="market_cap")` | Discriminator key is `market_cap`. |
| `networth_allocation_breakdown__empty.json` | `networth_allocation_breakdown(...)` | Empty slice: the echo keys are still present, `data` is `[]`. |
| `mf_sips__empty.json` | `mf_sips()` | Returned zero rows in the spike. |
| `indian_stocks_sips__empty.json` | `indian_stocks_sips()` | Returned zero rows in the spike. |
| `raw_mcp_envelope__networth_snapshot.json` | any tool, pre-unwrap | `{"result": "<stringified JSON>"}` — the wire format every tool on this server uses. |
| `rate_limit_error__tool_scope.json` | **any tool, when throttled** — mirrors the captured `rate_limit_envelope.json` | The 9-key `rate_limit_exceeded` body that **replaces** the payload on a throttled call, at the **per-tool** tier (`scope: "tool"`, `window: "tool:min"`). The MCP result carries `isError: false`, so this is what a "successful" response can actually contain. Shape verified against a real capture; every value here invented. See `docs/ind_money_payloads.md` §2.5. |
| `rate_limit_error__global_scope.UNVERIFIED.json` | same, **global** tier | ⚠️ The `scope: "global"` / `window: "min"` variant. The tier is real but **no capture of it was preserved** — only the key *values* differ from the verified file, so the shape is safe to test against while the tier itself stays flagged. |

## The edge cases in `networth_holdings__MF.json`

Six rows, in order:

1. **Healthy row** — every field populated, non-zero.
2. **`invested_amount` key absent entirely.** The vendor's own tool description
   says invested amount is often missing for linked (non-INDmoney) brokers.
   Parsers must not `KeyError`.
3. **`invested_amount: 0`** — the vendor's other stated shape for the same
   "unknown cost basis" case. `market_value − invested_amount` on this row
   fabricates a 100% gain; treat `0` as *unknown*, not as *invested nothing*.
4. **`invested_amount: null`** — the JSON-null variant of the same case.
5. **Zero-value holding** — `market_value`, `total_units`, `unit_price` and
   `holding_percent` all `0.0`, with a real non-zero `invested_amount` and a
   `-100.0` `pnl_per`. Guards against divide-by-zero in percentage math.
6. **Empty-string `broker` and empty-string `investment`, all numerics as
   `int`.** Both empty strings were observed in real rows, so `broker` is not a
   safe grouping/dedup key and `investment` is not a safe display label. The
   `int` typing is deliberate: the API emits `int` for integral values and
   `float` otherwise, **for the same field**, so models must use
   `float`/`Decimal` and tests must never assert on `type()`.

Also note: **`xirr` is `0` on every row in every fixture.** That mirrors reality
— it was `0` in 14 of 14 real rows. See Q1 in the payload doc; XIRR is not
obtainable from this data source.

## What these fixtures deliberately do **not** contain

- **No `currency` / `fx_rate` / `converted` field.** The real payloads have none
  at any level. If your code needs one, it must invent the assumption itself.
- **No date, `as_of`, cashflow or transaction field.** The real payloads have
  none anywhere. Anything time-based must be stamped by AlphaDesk at ingest.
- **No populated SIP rows.** Both SIP tools returned zero rows, so their row
  shape is unknown; guessing it here would be fiction dressed as a fixture.
- **The vendor's real classification labels.** `assetclass_l2`, `market_cap` and
  `sector` values here are invented placeholders. They are free-form strings in
  the API with no declared enum — do not hardcode label values against them in
  application code.

## Regeneration policy

These are **hand-written, never generated from a capture.** There is no
"regenerate" script by design — a script that transformed real payloads into
fixtures would be one bug away from committing real holdings to a public repo.

To refresh them after an API change:

1. Re-run the capture into a scratch directory outside the repo
   (procedure: `docs/TESTING/C2.md`).
2. Diff the **shapes only** against `docs/ind_money_payloads.md` §2, and update
   that doc first.
3. Re-synthesize the affected fixture **by hand** from the updated shape doc,
   inventing fresh values. Never copy-paste from a capture, not even a value you
   believe is harmless.
4. Re-run the leak check (`backend/tests/leak_check_ind_money.py`) against the
   scratch captures **before** staging anything.
5. Delete the scratch captures.

The highest-value refresh is a capture from an account that actually **holds
Indian stocks**, which would finally verify the `IND_STOCK` row shape and let
`networth_holdings__IND_STOCK__populated.UNVERIFIED.json` be renamed.
