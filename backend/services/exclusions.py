"""Holdings the user has excluded from every figure.

The source misreports some rows outright — #65's fixed deposits, a Rs 10,000
deposit reported at Rs 171 — and once the user has entered the real deposits by
hand (B10) those vendor rows are both wrong *and* double-counted. An exclusion
is the user saying "leave this row out of my numbers".

**Identity only, applied at read time.** A `holding_exclusions` row stores M1's
`(source, external_id)` pair plus display copies of the type and name; it never
stores a value. Every figure that reads holdings applies the set when it reads:

* `/portfolio/history` subtracts each excluded row's captured value from that
  day's total (`services.snapshots.history_points`),
* `/portfolio/movers` drops excluded rows before ranking,
* the AI overview computes its metrics from `apply_to_snapshot`'s output,
* the dashboard applies the same arithmetic to the live summary
  (`frontend/components/portfolio/exclusions.ts`).

Restoring a holding therefore re-prices everything exactly as excluding it did,
and no captured snapshot is ever rewritten.

**Manual rows are not excludable.** A manual deposit is the user's own data —
deleting it is the honest way to drop it — and keeping `source="manual"` out of
this table means history never has to reason about two overlays at once.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import HoldingExclusion, utcnow
from portfolio.models import (
    AllocationSlice,
    AssetType,
    Holding,
    PortfolioSnapshot,
    derive_pnl,
)
from tools.ind_money_auth import ensure_user_row

log = logging.getLogger(__name__)

#: `(source, external_id)` — M1's identity pair, the only thing matched on.
HoldingKey = tuple[str, str]

#: Rows with this source are user-authored (B10) and are deleted, not excluded.
MANUAL_SOURCE = "manual"


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
async def list_exclusions(session: AsyncSession, user_id: str) -> list[HoldingExclusion]:
    """``user_id``'s exclusions, oldest first."""
    rows = await session.execute(
        select(HoldingExclusion)
        .where(HoldingExclusion.user_id == user_id)
        .order_by(HoldingExclusion.created_at, HoldingExclusion.id)
    )
    return list(rows.scalars().all())


async def excluded_keys(session: AsyncSession, user_id: str) -> set[HoldingKey]:
    """The identity pairs ``user_id`` has excluded. Cheap: one indexed read."""
    rows = await session.execute(
        select(HoldingExclusion.source, HoldingExclusion.external_id).where(
            HoldingExclusion.user_id == user_id
        )
    )
    return {(source, external_id) for source, external_id in rows.all()}


async def exclude(
    session: AsyncSession,
    user_id: str,
    *,
    source: str,
    external_id: str,
    asset_type: str,
    name: Optional[str] = None,
) -> tuple[HoldingExclusion, bool]:
    """Exclude one holding. Idempotent: ``(row, created)``.

    Excluding a holding that is already excluded returns the existing row with
    ``created=False`` rather than a conflict — a second click on a button that
    already did its job is not an error worth showing anyone.
    """
    await ensure_user_row(session, user_id)
    result = await session.execute(
        pg_insert(HoldingExclusion)
        .values(
            id=uuid4().hex,
            user_id=user_id,
            source=source,
            external_id=external_id,
            asset_type=asset_type,
            name=name,
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(constraint="uq_holding_exclusions_user_holding")
        .returning(HoldingExclusion.id)
    )
    created = result.scalar_one_or_none() is not None
    await session.commit()
    row = await session.scalar(
        select(HoldingExclusion).where(
            HoldingExclusion.user_id == user_id,
            HoldingExclusion.source == source,
            HoldingExclusion.external_id == external_id,
        )
    )
    if row is None:  # pragma: no cover - inserted or already present a statement ago
        raise RuntimeError("exclusion vanished between insert and read")
    return row, created


async def restore(session: AsyncSession, user_id: str, exclusion_id: str) -> bool:
    """Drop one of ``user_id``'s exclusions; True if a row went."""
    result = await session.execute(
        sa_delete(HoldingExclusion).where(
            HoldingExclusion.user_id == user_id, HoldingExclusion.id == exclusion_id
        )
    )
    await session.commit()
    return bool(result.rowcount or 0)


async def safe_excluded_keys(
    session: Optional[AsyncSession], user_id: str
) -> set[HoldingKey]:
    """`excluded_keys`, degrading to "none" on any failure.

    Every reader of this set is additive to a page whose real content came from
    elsewhere; a failed exclusion read costs the adjustment, never the page.
    """
    if session is None:
        return set()
    try:
        return await excluded_keys(session, user_id)
    except Exception:  # noqa: BLE001 - see above
        log.warning("holding exclusions unavailable", exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001 - nothing left to salvage
            pass
        return set()


# --------------------------------------------------------------------------- #
# Applying the set to a snapshot
# --------------------------------------------------------------------------- #
def _bucket(asset_type: Optional[AssetType], raw: Optional[str]) -> Optional[str]:
    """Which `by_asset_type` slice a row belongs to.

    Out-of-enum buckets all coerce to `UNKNOWN`, so the source's own string is
    what tells two of them apart.
    """
    if asset_type is None:
        return None
    if asset_type is AssetType.UNKNOWN:
        return f"UNKNOWN:{(raw or '').strip().upper()}"
    return asset_type.value


def split(
    holdings: Iterable[Holding], keys: set[HoldingKey]
) -> tuple[list[Holding], list[Holding]]:
    """``(kept, excluded)``."""
    kept: list[Holding] = []
    dropped: list[Holding] = []
    for holding in holdings:
        (dropped if (holding.source, holding.external_id) in keys else kept).append(holding)
    return kept, dropped


def _reweighted(slices: Sequence[AllocationSlice]) -> list[AllocationSlice]:
    total = sum((s.current_value for s in slices), Decimal(0))
    if total <= 0:
        return list(slices)
    return [
        s
        if s.weight_pct is None
        else s.model_copy(
            update={
                "weight_pct": (s.current_value / total * Decimal(100)).quantize(
                    Decimal("0.01")
                )
            }
        )
        for s in slices
    ]


def apply_to_snapshot(
    snapshot: PortfolioSnapshot,
    holdings: Sequence[Holding],
    keys: set[HoldingKey],
) -> tuple[PortfolioSnapshot, list[Holding]]:
    """The snapshot and rows with the excluded holdings taken out.

    Each excluded row's value comes off its asset-type slice and off the
    headline totals, its cost basis off `invested_total`, and the P&L is
    re-derived from what is left through `derive_pnl` — the one place the
    cost-basis rules live.

    **Never more than the source counted.** A row is only subtracted from a
    bucket the snapshot actually reports, and never by more than that bucket's
    own value: #65's FD bucket has dropped out of the vendor's net worth on some
    days, and subtracting a row from a total that never included it would
    invent a loss of its own.

    Sector, cap-band and asset-class slices are left as reported — the source
    does not say which of them a given row sits in, and guessing would be worse
    than a slice that still includes it.
    """
    kept, dropped = split(holdings, keys)
    if not dropped:
        return snapshot, kept

    per_bucket: dict[str, tuple[Decimal, Decimal]] = {}
    for holding in dropped:
        bucket = _bucket(holding.asset_type, holding.asset_type_raw)
        if bucket is None:
            continue
        value, invested = per_bucket.get(bucket, (Decimal(0), Decimal(0)))
        per_bucket[bucket] = (
            value + holding.current_value,
            invested + (holding.invested_amount or Decimal(0)),
        )

    removed_value = Decimal(0)
    removed_invested = Decimal(0)
    slices: list[AllocationSlice] = []
    for item in snapshot.by_asset_type:
        bucket = _bucket(item.asset_type, item.asset_type_raw)
        if bucket is None or bucket not in per_bucket:
            slices.append(item)
            continue
        value, invested = per_bucket.pop(bucket)
        value = min(value, item.current_value)
        invested = (
            min(invested, item.invested_amount) if item.invested_amount is not None else Decimal(0)
        )
        removed_value += value
        removed_invested += invested
        left_value = item.current_value - value
        left_invested = (
            item.invested_amount - invested if item.invested_amount is not None else None
        )
        if left_invested is not None and left_invested <= 0:
            left_invested = None
        if left_value <= 0 and left_invested is None:
            continue  # the whole bucket was excluded
        pnl, pnl_pct = derive_pnl(left_value, left_invested)
        slices.append(
            item.model_copy(
                update={
                    "current_value": left_value,
                    "invested_amount": left_invested,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                }
            )
        )

    invested_total = snapshot.invested_total
    if invested_total is not None:
        invested_total = invested_total - removed_invested
        if invested_total <= 0:
            invested_total = None
    adjusted = snapshot.model_copy(
        update={
            "net_worth": snapshot.net_worth - removed_value,
            "gross_value": (
                snapshot.gross_value - removed_value
                if snapshot.gross_value is not None
                else None
            ),
            "invested_total": invested_total,
            "by_asset_type": _reweighted(slices),
        }
    )
    return adjusted, kept


__all__ = [
    "MANUAL_SOURCE",
    "HoldingKey",
    "apply_to_snapshot",
    "exclude",
    "excluded_keys",
    "list_exclusions",
    "restore",
    "safe_excluded_keys",
    "split",
]
