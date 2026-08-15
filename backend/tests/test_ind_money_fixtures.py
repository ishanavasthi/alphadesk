"""Validate the C2 synthetic IND Money fixtures.

These tests do NOT test application code — there is none yet (M1 is blocked on
the C2 human gate). They guard the fixtures themselves, so that whatever M1
builds is built against a fixture set that still means what
`docs/ind_money_payloads.md` says it means.

Two jobs:
  1. The fixtures stay structurally faithful to the documented payload shapes.
  2. The edge cases the payload doc relies on stay present — nobody "tidies
     up" the missing/null/zero `invested_amount` rows out of existence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "ind_money"

# Field names only — no values. Straight from docs/ind_money_payloads.md §2.2.
HOLDING_KEYS = {
    "asset_type", "assetclass_l2", "market_cap", "investment", "investment_code",
    "broker", "invested_amount", "market_value", "total_units", "unit_price",
    "total_pnl", "pnl_per", "holding_percent", "xirr",
}
# invested_amount is deliberately absent from one row, so it is not required.
REQUIRED_HOLDING_KEYS = HOLDING_KEYS - {"invested_amount"}

AGGREGATE_KEYS = {
    "invested_value", "current_value", "return", "return_percentage",
    "progress_value_percentage",
}

ASSET_TYPES = {
    "IND_STOCK", "MF", "US_STOCK", "BOND", "EPF", "NPS", "SA", "FD",
    "CRYPTO", "INSURANCE", "VEHICLE", "RE", "RD", "AIF", "PMS", "PPF",
}

HOLDINGS_FIXTURES = [
    "networth_holdings__MF.json",
    "networth_holdings__US_STOCK.json",
    "networth_holdings__single_holding.json",
    "networth_holdings__empty_asset_type.json",
    "networth_holdings__IND_STOCK__empty.json",
    "networth_holdings__IND_STOCK__populated.UNVERIFIED.json",
]

SNAPSHOT_FIXTURES = [
    "networth_snapshot.json",
    "networth_snapshot__single_holding.json",
    "networth_snapshot__empty.json",
]

BREAKDOWN_FIXTURES = {
    "networth_allocation_breakdown__MF__assets.json": "assetclass_l2",
    "networth_allocation_breakdown__MF__sector.json": "sector",
    "networth_allocation_breakdown__MF__market_cap.json": "market_cap",
    "networth_allocation_breakdown__empty.json": None,
}

# The rate-limit body (§2.5). Not a payload — it REPLACES one.
RATE_LIMIT_KEYS = {
    "error", "message", "scope", "window", "tool",
    "limit", "current", "cost", "retry_after_seconds",
}

RATE_LIMIT_FIXTURES = [
    "rate_limit_error__tool_scope.json",
    "rate_limit_error__global_scope.UNVERIFIED.json",
]

TOOL_NAMES = {
    "networth_snapshot", "networth_holdings", "networth_allocation_breakdown",
    "mf_sips", "indian_stocks_sips",
}


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def all_fixture_files():
    return sorted(p.name for p in FIXTURES.glob("*.json"))


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", all_fixture_files())
def test_fixture_is_valid_json(name):
    assert isinstance(load(name), dict)


@pytest.mark.parametrize("name", HOLDINGS_FIXTURES)
def test_holdings_rows_match_documented_shape(name):
    rows = load(name)["holdings"]
    for row in rows:
        assert set(row) <= HOLDING_KEYS, f"{name}: unknown key(s) {set(row) - HOLDING_KEYS}"
        assert REQUIRED_HOLDING_KEYS <= set(row), (
            f"{name}: missing {REQUIRED_HOLDING_KEYS - set(row)}"
        )
        assert row["asset_type"] in ASSET_TYPES


def test_ind_stock_uses_the_live_trading_envelope():
    """IND_STOCK does NOT return the plain {"holdings": [...]} shape."""
    for name in ("networth_holdings__IND_STOCK__empty.json",
                 "networth_holdings__IND_STOCK__populated.UNVERIFIED.json"):
        doc = load(name)
        assert len(doc) == 19, f"{name}: expected the 19-key live-trading envelope"
        for key in ("positions", "open_orders", "meta_info", "holding_error",
                    "is_pledge_eligible", "is_mtf_pledge_required"):
            assert key in doc, f"{name}: missing {key}"


@pytest.mark.parametrize("name", SNAPSHOT_FIXTURES)
def test_snapshot_shape(name):
    doc = load(name)
    assert AGGREGATE_KEYS  # sanity
    for key in ("total_networth", "total_current_value", "total_invested",
                "liabilities", "investments", "assets", "sector", "market_cap"):
        assert key in doc, f"{name}: missing {key}"
    for row in doc["investments"]:
        assert set(row) == AGGREGATE_KEYS | {"asset_type"}
    for row in doc["assets"]:
        assert set(row) == AGGREGATE_KEYS | {"assetclass_l2"}
    for row in doc["sector"]:
        assert set(row) == AGGREGATE_KEYS | {"sector"}
    for row in doc["market_cap"]:
        assert set(row) == AGGREGATE_KEYS | {"market_cap"}


@pytest.mark.parametrize("name,discriminator", BREAKDOWN_FIXTURES.items())
def test_breakdown_shape(name, discriminator):
    doc = load(name)
    assert set(doc) == {"asset_type", "breakdown_by", "data"}
    assert doc["asset_type"] in ASSET_TYPES
    assert doc["breakdown_by"] in {"assets", "sector", "market_cap"}
    for row in doc["data"]:
        assert set(row) == AGGREGATE_KEYS | {discriminator}


def test_raw_envelope_unwraps_to_a_snapshot():
    """Mirrors the {"result": "<stringified JSON>"} wire format every tool uses."""
    doc = load("raw_mcp_envelope__networth_snapshot.json")
    assert set(doc) == {"result"}
    assert isinstance(doc["result"], str)
    inner = json.loads(doc["result"])
    assert "total_networth" in inner


def test_sip_fixtures_are_empty_because_reality_was():
    assert load("mf_sips__empty.json") == {"mf_sips": []}
    assert load("indian_stocks_sips__empty.json") == {"indian_stocks_sips": []}


@pytest.mark.parametrize("name,scope,window", [
    ("rate_limit_error__tool_scope.json", "tool", "tool:min"),
    ("rate_limit_error__global_scope.UNVERIFIED.json", "global", "min"),
])
def test_rate_limit_envelope_shape(name, scope, window):
    """§2.5: a throttled call returns THIS instead of the payload, isError=False."""
    doc = load(name)
    assert set(doc) == RATE_LIMIT_KEYS
    assert doc["error"] == "rate_limit_exceeded"
    # scope and window are paired — reading one without the other misidentifies
    # which tier tripped, and the tiers have different limits.
    assert (doc["scope"], doc["window"]) == (scope, window)
    assert doc["tool"] in TOOL_NAMES


@pytest.mark.parametrize("name", RATE_LIMIT_FIXTURES)
def test_rate_limit_envelope_replaces_the_payload(name):
    """The error body carries NO payload key. Indexing data/holdings must fail."""
    doc = load(name)
    for payload_key in ("data", "holdings", "asset_type", "breakdown_by",
                        "total_networth", "investments"):
        assert payload_key not in doc, (
            f"{name}: a rate-limit body must not carry {payload_key!r} — the whole "
            "point is that the payload is gone, so ingest cannot index into it"
        )


@pytest.mark.parametrize("name", RATE_LIMIT_FIXTURES)
def test_rate_limit_counter_semantics(name):
    """`current` counts calls consumed BEFORE this one, and cost is what tips it.

    In the real capture `current` alone was still under `limit` — the server
    rejects a call whose *cost* would take it over. A client comparing only
    `current` to `limit` concludes it had budget left and retries immediately.
    """
    doc = load(name)
    assert doc["current"] < doc["limit"]
    assert doc["current"] + doc["cost"] > doc["limit"]
    assert doc["cost"] >= 1
    assert doc["retry_after_seconds"] > 0


# --------------------------------------------------------------------------
# Arithmetic the payload doc asserts about the real API (Q3)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", SNAPSHOT_FIXTURES)
def test_snapshot_totals_reconcile_internally(name):
    doc = load(name)
    total = doc["total_current_value"]
    assert abs(sum(r["current_value"] for r in doc["investments"]) - total) < 0.01
    assert abs(sum(r["current_value"] for r in doc["assets"]) - total) < 0.01
    assert abs(sum(r["invested_value"] for r in doc["investments"])
               - doc["total_invested"]) < 0.01
    # total_networth is NET of liabilities.
    assert abs(total - doc["liabilities"]["total"] - doc["total_networth"]) < 0.01


def test_snapshot_carries_the_unenumerable_wallet_bucket():
    """Q3: the holdings tool cannot enumerate every bucket the snapshot reports."""
    types = {r["asset_type"] for r in load("networth_snapshot.json")["investments"]}
    assert "US_STOCK_WALLET" in types
    assert "US_STOCK_WALLET" not in ASSET_TYPES, (
        "US_STOCK_WALLET must stay outside the holdings enum — that gap is the finding"
    )


# --------------------------------------------------------------------------
# The edge cases must not be tidied away
# --------------------------------------------------------------------------

def test_mf_fixture_keeps_every_invested_amount_edge_case():
    rows = load("networth_holdings__MF.json")["holdings"]
    # These three are genuinely different states and code must survive all of
    # them. Note .get() conflates the first two — which is exactly the trap
    # this fixture exists to expose, so test them apart.
    assert sum(1 for r in rows if "invested_amount" not in r) == 1, "missing-key row gone"
    assert sum(1 for r in rows
               if "invested_amount" in r and r["invested_amount"] is None) == 1, "null row gone"
    assert sum(1 for r in rows
               if r.get("invested_amount") == 0) == 1, "zero row gone"


def test_mf_fixture_keeps_a_zero_value_holding():
    rows = load("networth_holdings__MF.json")["holdings"]
    zeroed = [r for r in rows
              if r["market_value"] == 0 and r["total_units"] == 0 and r["unit_price"] == 0]
    assert len(zeroed) == 1
    assert zeroed[0].get("invested_amount"), "the zero-value row needs a real cost basis"


def test_mf_fixture_keeps_empty_broker_and_empty_name():
    rows = load("networth_holdings__MF.json")["holdings"]
    assert any(r["broker"] == "" for r in rows), "broker is not a safe grouping key"
    assert any(r["investment"] == "" for r in rows), "investment is not a safe label"


def test_mf_fixture_mixes_int_and_float_for_the_same_field():
    """The API emits int for integral values and float otherwise — models must
    not pin a type. If this ever fails, the fixture stopped exercising it."""
    rows = load("networth_holdings__MF.json")["holdings"]
    kinds = {type(r["market_value"]) for r in rows}
    assert kinds == {int, float}


def test_single_holding_and_empty_variants_exist():
    assert len(load("networth_holdings__single_holding.json")["holdings"]) == 1
    assert load("networth_holdings__empty_asset_type.json") == {"holdings": []}
    assert len(load("networth_snapshot__single_holding.json")["investments"]) == 1
    assert load("networth_snapshot__empty.json")["investments"] == []
    assert load("networth_allocation_breakdown__empty.json")["data"] == []


@pytest.mark.parametrize("name", HOLDINGS_FIXTURES)
def test_xirr_is_zero_everywhere_because_it_was_in_reality(name):
    for row in load(name)["holdings"]:
        assert row["xirr"] == 0, (
            "xirr was 0 in 14 of 14 real rows; a non-zero fixture would imply "
            "a capability this data source does not have (see Q1)"
        )


@pytest.mark.parametrize("name", all_fixture_files())
def test_no_currency_or_date_field_anywhere(name):
    """The real payloads carry neither. Fixtures must not invent one."""
    banned = ("currency", "fx_rate", "as_of", "date", "cashflow", "transaction")

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert not any(b in key.lower() for b in banned), f"{name}: {key}"
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(load(name))


def test_us_stock_row_has_no_currency_signal_beyond_asset_type():
    """Q4: asset_type is the ONLY thing distinguishing a foreign-denominated row."""
    row = load("networth_holdings__US_STOCK.json")["holdings"][0]
    assert row["asset_type"] == "US_STOCK"
    assert set(row) == HOLDING_KEYS
