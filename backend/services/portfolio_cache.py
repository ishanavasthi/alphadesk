"""Read-through cache for the `/portfolio/*` responses (issue #15).

The dashboard's expensive reads all go to the same place: a source that
rate-limits 15 calls per minute per tool and takes seconds to answer. Opening the
page twice in five minutes asked it the same questions twice, and a sector
drill-down that had already been fetched once today was fetched again on the next
visit. This module is the one indirection that stops both.

Four rules shape every function here, and they are the reason the cache cannot
become a liability:

1. **A cache is never load-bearing.** `session is None` (no `DATABASE_URL`) is a
   permanent miss and a silent no-op write — the deployment behaves exactly as it
   did before this file existed. Any *failure* to read or write degrades the same
   way, logged and swallowed, so a broken cache costs a slow page and never a
   dead one.
2. **Only successes are cached.** The routes call :func:`put` after a good read
   and never in an error path: caching a 429 or a 502 would turn a passing
   condition into a sticky one.
3. **Nothing here is history.** Every row is derived and re-readable, which is
   what makes :func:`prune` and :func:`invalidate_user` safe to run bluntly.
   `snapshot_days` is the record that must survive; this table is not.
4. **The key names the whole question.** Asset type, breakdown and — for the
   day-scoped allocation cache — the attributed IST day are all in the key, so a
   hit can only ever answer the question that was asked.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PortfolioCache

log = logging.getLogger(__name__)

#: How long a cached row is worth keeping at all. Two days rather than one
#: because the allocation cache is keyed by attributed IST day, and a row written
#: at 23:50 IST is still the answer for that day a few hours into the next one.
CACHE_RETENTION_DAYS = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def summary_key() -> str:
    return "summary"


def holdings_key(asset_type: str) -> str:
    return f"holdings:{asset_type}"


def allocation_key(asset_type: str, by: str, day: Any) -> str:
    """Allocation is cached **for the IST day**, so the day is part of the key.

    The day comes from `services.snapshots.attributed_day` — the one helper that
    owns calendar-day attribution in this codebase. Nothing here derives a day
    from UTC or from server-local "today"; a key that did would expire a
    drill-down at 05:30 IST for readers in India.
    """
    return f"allocation:{asset_type}:{by}:{day.isoformat()}"


async def get(
    session: Optional[AsyncSession],
    user_id: str,
    key: str,
    *,
    max_age: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """The cached payload for ``key``, or ``None`` for any kind of miss.

    ``max_age`` is a TTL in seconds; ``None`` means the key expires by its own
    name instead (the day-scoped allocation key). A row older than the TTL is
    left in place rather than deleted — the next successful read overwrites it,
    and the prune sweeps whatever never gets asked for again.
    """
    if session is None:
        return None
    try:
        row = (
            await session.execute(
                select(PortfolioCache).where(
                    PortfolioCache.user_id == user_id,
                    PortfolioCache.cache_key == key,
                )
            )
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - a cache miss is always a survivable answer
        log.warning("portfolio cache read failed for %s", key, exc_info=True)
        return None
    if row is None:
        return None
    if max_age is not None:
        fetched_at = row.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if (_now() - fetched_at).total_seconds() > max_age:
            return None
    return dict(row.payload)


async def put(
    session: Optional[AsyncSession],
    user_id: str,
    key: str,
    payload: dict[str, Any],
    *,
    as_of: Optional[datetime] = None,
) -> None:
    """Store ``payload`` under ``key``, replacing whatever was there.

    An upsert on ``(user_id, cache_key)`` rather than a delete-then-insert, so
    two concurrent loads of the same page cannot race into a unique violation.
    A user with no `users` row (single-tenant dev before anyone signs in) fails
    the foreign key — which is a miss forever, not an error the reader sees.
    """
    if session is None:
        return
    try:
        statement = pg_insert(PortfolioCache).values(
            user_id=user_id,
            cache_key=key,
            payload=payload,
            as_of=as_of,
            fetched_at=_now(),
        )
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_portfolio_cache_user_key",
                set_={
                    "payload": statement.excluded.payload,
                    "as_of": statement.excluded.as_of,
                    "fetched_at": statement.excluded.fetched_at,
                },
            )
        )
        await session.commit()
    except Exception:  # noqa: BLE001 - the reader already has their answer
        log.warning("portfolio cache write failed for %s", key, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001 - nothing left to salvage
            pass


async def invalidate_user(session: Optional[AsyncSession], user_id: str) -> int:
    """Drop every cached row for one user. Returns how many were removed.

    Called on unlink: the rows describe an account this user just disconnected,
    and serving them from cache afterwards would show holdings the app no longer
    has any right to read.
    """
    if session is None:
        return 0
    try:
        result = await session.execute(
            delete(PortfolioCache).where(PortfolioCache.user_id == user_id)
        )
        await session.commit()
    except Exception:  # noqa: BLE001 - unlinking must not fail on the cache
        log.warning("portfolio cache invalidation failed", exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001 - nothing left to salvage
            pass
        return 0
    return int(result.rowcount or 0)


async def prune(session: AsyncSession, days: int = CACHE_RETENTION_DAYS) -> int:
    """Delete cache rows older than ``days``. Returns the row count.

    Blunt on purpose. Unlike `snapshot_raw`, nothing is lost by deleting a row
    that is still current: the next reader pays one source call and it comes
    back.
    """
    if days < 1:
        raise ValueError("prune refuses a window under one day")
    cutoff = _now() - timedelta(days=days)
    result = await session.execute(
        delete(PortfolioCache).where(PortfolioCache.fetched_at < cutoff)
    )
    await session.commit()
    return int(result.rowcount or 0)


__all__ = [
    "CACHE_RETENTION_DAYS",
    "allocation_key",
    "get",
    "holdings_key",
    "invalidate_user",
    "prune",
    "put",
    "summary_key",
]
