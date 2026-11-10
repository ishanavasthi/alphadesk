"""`services.exclusions.apply_to_snapshot` — the arithmetic, no database.

The motivating rows are #65's: two vendor fixed deposits reported at a fraction
of their principal (Rs 10,000 at Rs 171, Rs 5,000 at Rs 162) that the user has
re-entered by hand and wants out of every figure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from portfolio.models import AllocationSlice, AssetType, Holding, PortfolioSnapshot
from services.exclusions import apply_to_snapshot

AS_OF = datetime(2026, 11, 10, tzinfo=timezone.utc)


def _holding(external_id: str, asset_type: AssetType, value: str, invested: str | None) -> Holding:
    return Holding(
        source="ind_money",
        external_id=external_id,
        asset_type=asset_type,
        current_value=Decimal(value),
        invested_amount=Decimal(invested) if invested else None,
        as_of=AS_OF,
    )


FD_A = _holding("FD:A", AssetType.FD, "171", "10000")
FD_B = _holding("FD:B", AssetType.FD, "162", "5000")
FUND = _holding("MF:X", AssetType.MF, "120000", "100000")


def _snapshot(fd_value: str = "333", fd_invested: str = "15000") -> PortfolioSnapshot:
    return PortfolioSnapshot(
        source="ind_money",
        as_of=AS_OF,
        net_worth=Decimal("120000") + Decimal(fd_value),
        gross_value=Decimal("120000") + Decimal(fd_value),
        invested_total=Decimal("100000") + Decimal(fd_invested),
        by_asset_type=[
            AllocationSlice(
                label="MF",
                asset_type=AssetType.MF,
                current_value=Decimal("120000"),
                invested_amount=Decimal("100000"),
                weight_pct=Decimal("99.72"),
            ),
            AllocationSlice(
                label="FD",
                asset_type=AssetType.FD,
                current_value=Decimal(fd_value),
                invested_amount=Decimal(fd_invested),
                weight_pct=Decimal("0.28"),
            ),
        ],
    )


def test_no_exclusions_is_the_identity() -> None:
    snapshot = _snapshot()
    adjusted, kept = apply_to_snapshot(snapshot, [FD_A, FD_B, FUND], set())
    assert adjusted is snapshot
    assert kept == [FD_A, FD_B, FUND]


def test_excluding_both_fds_removes_their_value_basis_and_bucket() -> None:
    keys = {("ind_money", "FD:A"), ("ind_money", "FD:B")}
    adjusted, kept = apply_to_snapshot(_snapshot(), [FD_A, FD_B, FUND], keys)

    assert kept == [FUND]
    assert adjusted.net_worth == Decimal("120000")
    assert adjusted.gross_value == Decimal("120000")
    assert adjusted.invested_total == Decimal("100000")
    # The FD bucket is gone entirely, and the fund is the whole portfolio now.
    assert [s.label for s in adjusted.by_asset_type] == ["MF"]
    assert adjusted.by_asset_type[0].weight_pct == Decimal("100.00")


def test_excluding_one_fd_leaves_the_rest_of_its_bucket_with_a_rederived_return() -> None:
    adjusted, kept = apply_to_snapshot(
        _snapshot(), [FD_A, FD_B, FUND], {("ind_money", "FD:A")}
    )
    assert kept == [FD_B, FUND]
    fd = next(s for s in adjusted.by_asset_type if s.asset_type is AssetType.FD)
    assert fd.current_value == Decimal("162")
    assert fd.invested_amount == Decimal("5000")
    assert fd.pnl == Decimal("-4838")
    assert adjusted.invested_total == Decimal("105000")


def test_never_subtracts_more_than_the_bucket_the_source_counted() -> None:
    """#65: the FD bucket has dropped out of the vendor's totals on some days.

    The rows still arrive, but subtracting them from a total that never
    included them would invent a loss. The cap is the bucket's own value.
    """
    snapshot = _snapshot(fd_value="100", fd_invested="5000")
    adjusted, _ = apply_to_snapshot(
        snapshot, [FD_A, FD_B, FUND], {("ind_money", "FD:A"), ("ind_money", "FD:B")}
    )
    assert adjusted.net_worth == Decimal("120000")
    assert adjusted.invested_total == Decimal("100000")


def test_a_bucket_the_snapshot_does_not_report_subtracts_nothing() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "net_worth": Decimal("120000"),
            "gross_value": Decimal("120000"),
            "invested_total": Decimal("100000"),
            "by_asset_type": _snapshot().by_asset_type[:1],
        }
    )
    adjusted, kept = apply_to_snapshot(snapshot, [FD_A, FUND], {("ind_money", "FD:A")})
    assert kept == [FUND]
    assert adjusted.net_worth == Decimal("120000")
    assert adjusted.invested_total == Decimal("100000")


def test_unknown_cost_basis_is_not_subtracted_from_invested() -> None:
    bare = _holding("FD:C", AssetType.FD, "50", None)
    snapshot = _snapshot(fd_value="383")
    adjusted, _ = apply_to_snapshot(snapshot, [FD_A, FD_B, bare, FUND], {("ind_money", "FD:C")})
    assert adjusted.net_worth == Decimal("120333")
    assert adjusted.invested_total == Decimal("115000")
