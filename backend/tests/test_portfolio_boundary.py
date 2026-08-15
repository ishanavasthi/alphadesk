"""The connector boundary, enforced by grep rather than by good intentions.

`backend/portfolio/connectors/` is the only place a vendor's field names may
appear. Everywhere else — the model, the errors, anything a later card builds on
top — speaks the normalized vocabulary. Without this test the boundary erodes
one convenient `row["pnl_per"]` at a time, and swapping in a second source stops
being possible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PORTFOLIO = Path(__file__).resolve().parents[1] / "portfolio"
CONNECTORS = PORTFOLIO / "connectors"

#: IND Money's own key names, from `docs/ind_money_payloads.md` §2. Note what is
#: deliberately NOT here: `invested_amount`, `current_value`, `asset_type` and
#: `market_cap` are the *model's* names too — banning them would be banning our
#: own vocabulary. These are the vendor-only ones.
VENDOR_FIELD_NAMES = [
    "pnl_per",
    "holding_percent",
    "market_value",
    "investment_code",
    "assetclass_l2",
    "total_networth",
    "total_current_value",
    "total_invested",
    "invested_value",
    "unit_price",
    "total_units",
    "total_pnl",
    "progress_value_percentage",
    "return_percentage",
    "xirr",
    "holding_error",
    "is_pledge_eligible",
    "is_mtf_pledge_required",
    "intra_day_positions",
    "is_cached_response",
]

#: The vendor's tool names are equally leaky: a caller that knows them is
#: coupled to the source it was supposed to be insulated from.
VENDOR_TOOL_NAMES = [
    "networth_snapshot",
    "networth_holdings",
    "networth_allocation_breakdown",
    "mf_sips",
    "indian_stocks_sips",
]


def files_above_the_boundary() -> list[Path]:
    return sorted(
        path
        for path in PORTFOLIO.rglob("*.py")
        if CONNECTORS not in path.parents and path.parent != CONNECTORS
    )


def test_there_is_something_above_the_boundary_to_check():
    """A vacuous grep passes forever. Prove it has files to look at."""
    names = {path.name for path in files_above_the_boundary()}
    assert {"models.py", "errors.py"} <= names


@pytest.mark.parametrize("name", VENDOR_FIELD_NAMES + VENDOR_TOOL_NAMES)
def test_no_vendor_name_appears_above_the_connector_boundary(name):
    offenders = [
        str(path.relative_to(PORTFOLIO))
        for path in files_above_the_boundary()
        if name in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"vendor name {name!r} leaked above the connector boundary in "
        f"{offenders} — the model must not know what any one source calls its "
        "fields"
    )


def test_the_grep_would_actually_catch_a_leak():
    """Non-vacuity: the same names DO appear below the boundary, so a file that
    moved the wrong way would be caught rather than silently passing."""
    below = "\n".join(
        path.read_text(encoding="utf-8") for path in CONNECTORS.glob("*.py")
    )
    for name in ("pnl_per", "market_value", "investment_code", "networth_holdings"):
        assert name in below, f"{name} should exist in connectors/ — check the fixture"


def test_the_model_layer_does_not_import_the_ind_money_client():
    """An import is a leak too, and a harder one to see than a field name."""
    for path in files_above_the_boundary():
        text = path.read_text(encoding="utf-8")
        assert "tools.ind_money" not in text, path
        assert "portfolio.connectors" not in text or path.name == "__init__.py", path
