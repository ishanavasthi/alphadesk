"""The model's own rules (card M1).

Each test here corresponds to a finding in `docs/ind_money_payloads.md`. The
point is that these rules are enforced by the *type*, so a future connector
cannot opt out of them by forgetting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from portfolio.models import (
    CURRENCY,
    Allocation,
    AllocationSlice,
    AssetType,
    BreakdownBy,
    Holding,
    LinkHealth,
    PortfolioSnapshot,
    Sip,
    SipKind,
    derive_pnl,
    is_us_exposure,
    stable_external_id,
    to_decimal,
    sum_holdings_value,
)

NOW = datetime(2026, 8, 15, 6, 30, tzinfo=timezone.utc)

#: The 16 values the server's own input schema declares (C2 §1). UNKNOWN is
#: ours, not the vendor's, and must never be sent as a query argument.
VENDOR_ASSET_TYPES = {
    "IND_STOCK", "MF", "US_STOCK", "BOND", "EPF", "NPS", "SA", "FD",
    "CRYPTO", "INSURANCE", "VEHICLE", "RE", "RD", "AIF", "PMS", "PPF",
}


def holding(**overrides) -> Holding:
    kwargs = {
        "source": "stub",
        "external_id": "X1",
        "asset_type": AssetType.MF,
        "current_value": 100,
        "as_of": NOW,
    }
    kwargs.update(overrides)
    return Holding(**kwargs)


# --------------------------------------------------------------------------
# Rule 1 — Decimal everywhere, coerced through str
# --------------------------------------------------------------------------

def test_to_decimal_goes_through_str_not_binary_float():
    # Decimal(0.1) is 0.1000000000000000055511151231257827021181583404541015625.
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(1.15) == Decimal("1.15")


def test_the_same_field_may_arrive_as_int_or_float():
    """The API emits `5` for an integral value and `5.0` otherwise, per row."""
    assert to_decimal(30000) == to_decimal(30000.0) == Decimal("30000")
    assert isinstance(holding(current_value=3).current_value, Decimal)
    assert isinstance(holding(current_value=3.5).current_value, Decimal)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_to_decimal_treats_absent_as_none(value):
    assert to_decimal(value) is None


@pytest.mark.parametrize("value", [True, False, "abc", object()])
def test_to_decimal_refuses_non_numbers(value):
    with pytest.raises(ValueError):
        to_decimal(value)


def test_every_money_field_on_a_holding_is_decimal():
    h = holding(
        units=10, avg_cost=9, invested_amount=90.0, current_price=10,
        current_value=100, pnl=10, pnl_pct=11.11,
    )
    for field in ("units", "avg_cost", "invested_amount", "current_price",
                  "current_value", "pnl", "pnl_pct"):
        assert isinstance(getattr(h, field), Decimal), field


# --------------------------------------------------------------------------
# Rule 2 — invested_amount == 0 means UNKNOWN, and unknown cost basis has no P&L
# --------------------------------------------------------------------------

def test_zero_cost_basis_is_rejected_by_the_model():
    """0 is the vendor's stand-in for missing; a connector must map it to None."""
    with pytest.raises(ValueError, match="UNKNOWN cost basis"):
        holding(invested_amount=0)


def test_no_pnl_may_accompany_an_unknown_cost_basis():
    with pytest.raises(ValueError, match="cost basis is unknown"):
        holding(invested_amount=None, pnl=100)
    with pytest.raises(ValueError, match="cost basis is unknown"):
        holding(invested_amount=None, pnl_pct=-100)


def test_a_known_cost_basis_may_carry_a_zero_return():
    """Cash-like rows legitimately return 0 — that is 'no return by nature'."""
    h = holding(invested_amount=100, pnl=0, pnl_pct=0)
    assert h.pnl == 0 and h.pnl_pct == 0


@pytest.mark.parametrize("invested", [None, Decimal(0)])
def test_derive_pnl_refuses_to_invent_a_return(invested):
    assert derive_pnl(Decimal("50000"), invested) == (None, None)


def test_derive_pnl_when_the_cost_basis_is_known():
    pnl, pct = derive_pnl(Decimal("110"), Decimal("100"))
    assert (pnl, pct) == (Decimal("10"), Decimal("10.00"))


def test_derive_pnl_on_a_worthless_holding_is_a_real_minus_100():
    """A zero *value* with a known cost basis is a genuine total loss —
    unlike a zero *cost basis*, which is simply unknown."""
    assert derive_pnl(Decimal("0"), Decimal("15000")) == (Decimal("-15000"), Decimal("-100.00"))


def test_the_same_rule_applies_to_allocation_slices():
    with pytest.raises(ValueError):
        AllocationSlice(label="MF", current_value=10, invested_amount=0)
    with pytest.raises(ValueError):
        AllocationSlice(label="MF", current_value=10, pnl_pct=5)


# --------------------------------------------------------------------------
# Rule 3 — as_of is stamped, never parsed out of a payload
# --------------------------------------------------------------------------

def test_as_of_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        holding(as_of=datetime(2026, 8, 15, 6, 30))


def test_as_of_is_normalized_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    h = holding(as_of=datetime(2026, 8, 15, 12, 0, tzinfo=ist))
    assert h.as_of == datetime(2026, 8, 15, 6, 30, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Rule 4 — one currency, and it is an assumption the model refuses to bend
# --------------------------------------------------------------------------

@pytest.mark.parametrize("model_kwargs", [
    {"currency": "USD"},
    {"currency": ""},
])
def test_non_inr_is_rejected(model_kwargs):
    with pytest.raises(ValueError, match="INR"):
        holding(**model_kwargs)


def test_currency_defaults_to_inr_everywhere():
    assert holding().currency == CURRENCY
    assert AllocationSlice(label="x", current_value=1).currency == CURRENCY
    assert PortfolioSnapshot(source="s", as_of=NOW, net_worth=1).currency == CURRENCY


def test_us_exposure_is_signalled_by_asset_type_not_by_a_currency_field():
    assert is_us_exposure(AssetType.US_STOCK)
    # The un-enumerable wallet bucket is outside the enum but still US exposure.
    assert is_us_exposure(AssetType.UNKNOWN, "US_STOCK_WALLET")
    assert not is_us_exposure(AssetType.IND_STOCK)
    assert not is_us_exposure(AssetType.UNKNOWN, "SOMETHING_ELSE")
    assert holding(asset_type=AssetType.US_STOCK).is_us_exposure


# --------------------------------------------------------------------------
# Asset types: 16 queryable values plus a sentinel that never crashes
# --------------------------------------------------------------------------

def test_the_queryable_asset_types_are_exactly_the_vendors_sixteen():
    assert {a.value for a in AssetType.queryable()} == VENDOR_ASSET_TYPES
    assert AssetType.UNKNOWN not in AssetType.queryable()


@pytest.mark.parametrize("raw", ["US_STOCK_WALLET", "SOMETHING_NEW", "", None, 17, []])
def test_unknown_asset_type_strings_never_raise(raw):
    assert AssetType.coerce(raw) is AssetType.UNKNOWN


def test_asset_type_coercion_is_case_and_space_tolerant():
    assert AssetType.coerce(" mf ") is AssetType.MF
    assert AssetType.coerce(AssetType.FD) is AssetType.FD


def test_an_unknown_asset_type_keeps_its_original_string():
    h = holding(asset_type=AssetType.UNKNOWN, asset_type_raw="US_STOCK_WALLET")
    assert h.asset_type_raw == "US_STOCK_WALLET"


# --------------------------------------------------------------------------
# Identity, aggregates and the things this model deliberately does not have
# --------------------------------------------------------------------------

def test_stable_external_id_is_deterministic_and_field_sensitive():
    assert stable_external_id("a", "b") == stable_external_id("a", "b")
    assert stable_external_id("a", "b") != stable_external_id("a", "c")
    assert stable_external_id("a|b") != stable_external_id("a", "b")


def test_sum_holdings_value_is_a_sum_of_rows_not_a_net_worth():
    holdings = [holding(external_id="a", current_value=10),
                holding(external_id="b", current_value=2.5)]
    assert sum_holdings_value(holdings) == Decimal("12.5")
    assert sum_holdings_value([]) == Decimal(0)


def test_snapshot_totals_are_passed_through_and_never_reconciled():
    snap = PortfolioSnapshot(
        source="s", as_of=NOW, net_worth=850000, gross_value=1000000,
        by_asset_type=[AllocationSlice(label="MF", current_value=1)],
    )
    # The snapshot total has nothing to do with the slices it carries — that is
    # the whole point (an un-enumerable bucket plus per-type residuals).
    assert snap.net_worth == Decimal("850000")
    assert snap.by_asset_type[0].current_value == Decimal("1")


def test_no_model_has_an_xirr_field():
    """C2 Q1: the vendor field is dead and no cashflow exists to compute one."""
    for model in (Holding, AllocationSlice, Allocation, PortfolioSnapshot, Sip):
        assert not any("xirr" in name.lower() for name in model.model_fields), model


def test_models_reject_unknown_fields():
    with pytest.raises(ValueError):
        holding(some_vendor_field=1)


def test_enums_cover_the_documented_vocabularies():
    assert {b.value for b in BreakdownBy} == {"assets", "sector", "market_cap"}
    assert {h.value for h in LinkHealth} == {
        "linked", "expiring", "needs_relink", "revoked"
    }
    assert {k.value for k in SipKind} == {"mf", "ind_stock"}
