"""Deterministic metrics (card A1, item 1) — the three degenerate portfolios.

Every number the overview may cite is computed here; these pin that a
one-holding book, a no-cost-basis book and an empty book each produce sane
metrics (or explicit unavailability), never a crash or a fabricated figure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from agents.portfolio.metrics import (
    HistoryPoint,
    compute_metrics,
    metrics_by_key,
)
from portfolio.models import AllocationSlice, AssetType, Holding, PortfolioSnapshot

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _holding(external_id: str, value: str, *, invested: str | None, name: str, atype: str = "MF") -> Holding:
    inv = None if invested is None else Decimal(invested)
    cur = Decimal(value)
    pnl = None if inv is None else cur - inv
    pnl_pct = None if inv is None or inv == 0 else (pnl / inv * Decimal(100)).quantize(Decimal("0.01"))
    return Holding(
        source="stub",
        external_id=external_id,
        asset_type=AssetType(atype),
        name=name,
        invested_amount=inv,
        current_value=cur,
        pnl=pnl,
        pnl_pct=pnl_pct,
        as_of=NOW,
    )


def _snapshot(**kwargs) -> PortfolioSnapshot:
    defaults = dict(source="stub", as_of=NOW, net_worth=Decimal("0"))
    defaults.update(kwargs)
    return PortfolioSnapshot(**defaults)


# --------------------------------------------------------------------------- #
def test_one_holding_gives_a_concentration_warning_not_a_crash() -> None:
    snap = _snapshot(net_worth=Decimal("100000"), gross_value=Decimal("100000"), invested_total=Decimal("90000"))
    holdings = [_holding("H1", "100000", invested="90000", name="Only Fund")]
    by_key = metrics_by_key(compute_metrics(snap, holdings))

    hhi = by_key["herfindahl_index"]
    assert hhi.available
    assert hhi.value == Decimal("1")
    assert hhi.detail == "concentrated"
    top = by_key["top_holding_weight"]
    assert top.display == "100.0%"
    assert by_key["top3_weight"].display == "100.0%"
    assert by_key["top_holding_name"].text == "Only Fund"


def test_no_cost_basis_anywhere_makes_no_performance_claim() -> None:
    snap = _snapshot(net_worth=Decimal("50000"), gross_value=Decimal("50000"), invested_total=None)
    holdings = [
        _holding("H1", "30000", invested=None, name="Fund A"),
        _holding("H2", "20000", invested=None, name="Fund B"),
    ]
    by_key = metrics_by_key(compute_metrics(snap, holdings))

    # Performance metrics are explicitly unavailable — not a fabricated 0/-100%.
    assert by_key["pnl"].available is False
    assert by_key["pnl"].display == "—"
    assert by_key["pnl_pct"].available is False
    assert by_key["invested_total"].available is False
    # Every row is flagged as missing a basis, and concentration still works.
    rows = by_key["rows_without_cost_basis"]
    assert rows.value == Decimal("2")
    assert rows.detail == "of 2"
    assert by_key["herfindahl_index"].available is True


def test_empty_portfolio_does_not_crash_and_degrades_cleanly() -> None:
    snap = _snapshot(net_worth=Decimal("0"), gross_value=Decimal("0"))
    by_key = metrics_by_key(compute_metrics(snap, []))

    assert by_key["holdings_count"].value == Decimal("0")
    for key in ("herfindahl_index", "top_holding_weight", "top3_weight", "equity_share"):
        assert by_key[key].available is False
        assert by_key[key].display == "—"


def test_equity_and_us_exposure_from_snapshot_slices() -> None:
    slices = [
        AllocationSlice(label="IND_STOCK", asset_type=AssetType.IND_STOCK, asset_type_raw="IND_STOCK", current_value=Decimal("300000")),
        AllocationSlice(label="US_STOCK", asset_type=AssetType.US_STOCK, asset_type_raw="US_STOCK", current_value=Decimal("100000")),
        AllocationSlice(label="US_STOCK_WALLET", asset_type=AssetType.UNKNOWN, asset_type_raw="US_STOCK_WALLET", current_value=Decimal("20000")),
        AllocationSlice(label="FD", asset_type=AssetType.FD, asset_type_raw="FD", current_value=Decimal("80000")),
    ]
    snap = _snapshot(net_worth=Decimal("500000"), gross_value=Decimal("500000"), by_asset_type=slices)
    by_key = metrics_by_key(compute_metrics(snap, []))
    # (300000 + 100000 + 20000) / 500000 = 84.0%
    assert by_key["equity_share"].display == "84.0%"
    # US = 100000 + 20000 = 24.0%
    assert by_key["us_exposure_share"].display == "24.0%"


def test_week_over_week_delta_needs_a_week_of_snapshots() -> None:
    snap = _snapshot(net_worth=Decimal("100000"), gross_value=Decimal("100000"))
    # No history → unavailable, with an honest reason, never a fabricated 0.
    empty = metrics_by_key(compute_metrics(snap, []))
    assert empty["wow_networth_delta"].available is False

    from datetime import date

    history = [
        HistoryPoint(day=date(2026, 8, 9), net_worth=Decimal("990000")),
        HistoryPoint(day=date(2026, 8, 16), net_worth=Decimal("1000000")),
    ]
    with_hist = metrics_by_key(compute_metrics(snap, [], history=history))
    wow = with_hist["wow_networth_delta"]
    assert wow.available is True
    assert wow.display == "+₹10,000"
    assert with_hist["wow_networth_delta_pct"].available is True
