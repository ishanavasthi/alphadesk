"""Daily portfolio snapshots — capture, read back, prune (card S1).

**A missed snapshot can never be backfilled.** The source is point-in-time: it
answers "what is your net worth *now*" and nothing else. No payload carries a
date (C2), there is no historical endpoint, and no amount of durable storage
invents a row for a day the job never ran. So every decision in this module is
about surviving an *acquisition* failure, not a storage failure:

- three independent nets fire at the same day (the 23:45 IST cron, the ~01:00
  IST retry, and an opportunistic capture when someone opens the dashboard),
  all three converging on one row through one idempotency key;
- one user's dead link, one throttled bucket or one failed FX call degrades that
  part and writes the rest, because a partial snapshot is worth infinitely more
  than the nothing that is the alternative;
- the day a capture *is* attributed to comes from a single helper
  (:func:`attributed_day`) rather than from `date.today()` anywhere, so a run
  that slips past midnight IST still lands on the day it was meant for.

Everything that touches the source goes through the M1 connector interface —
this module never imports `tools/ind_money.py` and no vendor field name appears
in it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import httpx
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    BrokerLink,
    SnapshotDay,
    SnapshotHolding,
    SnapshotRaw,
    User,
    utcnow,
)
from db.session import ENV_VAR as DATABASE_URL_ENV
from db.session import get_sessionmaker
from portfolio.connectors import LOCAL_USER_ID, PortfolioConnector
from portfolio.errors import (
    NotLinked,
    PortfolioSourceError,
    RateLimited,
    UnsupportedAssetType,
)
from portfolio.models import AssetType, Holding, PortfolioSnapshot

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Calendar-day attribution — the one IST helper, used everywhere
# --------------------------------------------------------------------------- #
#: India Standard Time as a **fixed** UTC offset.
#:
#: Deliberately not `zoneinfo.ZoneInfo("Asia/Kolkata")`: India has observed no
#: daylight saving since 1945, so the offset is a constant, and depending on the
#: tz database would make attribution depend on whether the runtime image
#: happens to ship one. A snapshot landing on the wrong day because a slim
#: container has no `/usr/share/zoneinfo` is exactly the silent failure this
#: module exists to prevent.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

#: Runs before this IST hour are attributed to the **previous** IST calendar
#: day.
#:
#: The primary capture is ~23:45 IST (after mutual-fund NAVs publish ~23:00),
#: with a retry ~01:00 IST. Without a cutoff the retry would file itself under
#: tomorrow and the day it was retrying would stay empty forever. 06:00 is far
#: enough past the retry to cover a badly-delayed GitHub cron — schedules there
#: are explicitly best-effort — and far enough before the next primary run that
#: it can never swallow a real day.
ATTRIBUTION_CUTOFF_HOUR = 6


def attributed_day(now: datetime) -> date:
    """The IST calendar day a capture taken at ``now`` belongs to.

    ``now`` must be timezone-aware. A naive datetime is rejected rather than
    assumed to be UTC or local: guessing here is how a snapshot silently lands
    on the wrong day, and a wrong day cannot be corrected later because the
    source cannot be asked again.
    """
    if now.tzinfo is None:
        raise ValueError(
            "attributed_day() needs a timezone-aware datetime — a naive one "
            "would be attributed from server-local or UTC 'today', which is the "
            "exact bug the IST cutoff exists to prevent"
        )
    ist = now.astimezone(IST)
    if ist.hour < ATTRIBUTION_CUTOFF_HOUR:
        return (ist - timedelta(days=1)).date()
    return ist.date()


def last_expected_day(now: datetime) -> date:
    """The newest attributed day a capture is definitely *due* for by ``now``.

    One day behind :func:`attributed_day`, and that gap is the point. While the
    current attributed day is ``A`` — i.e. from 06:00 IST on ``A`` until 06:00
    IST on ``A+1`` — ``A``'s own capture has not necessarily happened yet: it
    runs at 23:45 IST on ``A``, near the end of that window, and may retry at
    ~01:00 IST. ``A-1``'s capture, by contrast, had both its chances. Expecting
    ``A`` would make the banner shout at breakfast every single morning, which
    trains the reader to ignore it — and a staleness banner nobody reads is
    worse than none.
    """
    return attributed_day(now) - timedelta(days=1)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# USD/INR reference rate
# --------------------------------------------------------------------------- #
#: Keyless ECB reference rate (operator decision, 2026-08-15). Shape:
#: ``{"date": "2026-08-14", "base": "USD", "quote": "INR", "rate": 87.4}``.
FX_URL = "https://api.frankfurter.dev/v2/rate/USD/INR"
FX_TIMEOUT_SECONDS = 10.0

FxFetcher = Callable[[], Awaitable[Optional[Decimal]]]


async def fetch_usd_inr(*, timeout: float = FX_TIMEOUT_SECONDS) -> Optional[Decimal]:
    """The day's USD/INR reference rate, or ``None`` on any failure.

    **This function must never raise.** The rate is display math for the
    US-exposure badge (M1 §4 — holdings stay vendor-INR and are never re-summed
    through it); the snapshot is data that cannot be re-acquired. Trading the
    second for the first would be an obviously bad bargain, so every failure —
    DNS, timeout, 5xx, a reshaped body, a non-numeric rate — degrades to NULL
    and a log line.

    ECB publishes once per working day (~20:30 IST), so the 23:45 IST run gets
    same-day data and a weekend run stores the most recent published rate. That
    is the correct answer for a weekend, not a stale one: no rate was published.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(FX_URL)
            response.raise_for_status()
            body = response.json()
        rate = Decimal(str(body["rate"]))
        if not rate.is_finite() or rate <= 0:
            raise ValueError(f"implausible rate: {rate}")
        return rate
    except Exception as exc:  # noqa: BLE001 - the FX call may never fail a capture
        log.warning("USD/INR fetch failed (%s: %s); storing NULL", type(exc).__name__, exc)
        return None


# --------------------------------------------------------------------------- #
# Report types
# --------------------------------------------------------------------------- #
#: What happened to one user in one capture run. `reason` is always one of our
#: own fixed strings — never a source-supplied message, which can quote payload
#: fragments and would end up in an HTTP response body.
CAPTURED = "captured"
ALREADY_CAPTURED = "already_captured"
SKIPPED = "skipped"
FAILED = "failed"


#: Why one bucket's rows could not be read. Our own vocabulary, never the
#: source's message text.
BUCKET_THROTTLED = "throttled"
BUCKET_UNSUPPORTED = "unsupported"
BUCKET_SOURCE_ERROR = "source_error"


@dataclass(frozen=True)
class BucketFailure:
    """One asset type the snapshot reported but whose rows could not be read.

    Persisted, not merely reported. Without a stored record, a day captured with
    an unreadable bucket is **indistinguishable from a day where that bucket was
    genuinely empty** — the rows are absent either way, and "you held no mutual
    funds on the 14th" is a false statement about somebody's money rather than a
    missing log line.
    """

    asset_type: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"asset_type": self.asset_type, "reason": self.reason}


@dataclass(frozen=True)
class UserOutcome:
    user_id: str
    status: str
    captured_on: date
    reason: Optional[str] = None
    holdings: int = 0
    #: Buckets the snapshot reported but whose rows could not be read. The day
    #: is still written — `total_value` is the figure history is drawn from, and
    #: it comes from the snapshot call, not from these — and the list is stored
    #: on the row (`snapshot_days.buckets_failed`) so the partiality outlives
    #: this response.
    buckets_failed: tuple[BucketFailure, ...] = ()
    #: True when the day's row exists but carries no FX rate.
    fx_missing: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "status": self.status,
            "reason": self.reason,
            "holdings": self.holdings,
            "buckets_failed": [f.as_dict() for f in self.buckets_failed],
            "fx_missing": self.fx_missing,
        }


@dataclass(frozen=True)
class CaptureReport:
    captured_on: date
    outcomes: tuple[UserOutcome, ...] = field(default_factory=tuple)

    @property
    def users_captured(self) -> int:
        return sum(1 for o in self.outcomes if o.status == CAPTURED)

    @property
    def skipped(self) -> int:
        """Users deliberately not captured — a dead link, or already done today.

        Separated from `errors` because an operator reading a red run needs to
        know whether something is broken or whether the retry simply had nothing
        to do.
        """
        return sum(1 for o in self.outcomes if o.status in (SKIPPED, ALREADY_CAPTURED))

    @property
    def errors(self) -> int:
        return sum(1 for o in self.outcomes if o.status == FAILED)

    def as_dict(self) -> dict[str, Any]:
        return {
            "captured_on": self.captured_on.isoformat(),
            "users_captured": self.users_captured,
            "skipped": self.skipped,
            "errors": self.errors,
            "details": [o.as_dict() for o in self.outcomes],
        }


# --------------------------------------------------------------------------- #
# Capture
# --------------------------------------------------------------------------- #
#: Seconds between per-bucket source calls.
#:
#: The source allows 15 calls/min per tool and 30/min overall. A capture makes
#: one snapshot call plus one holdings call per non-empty bucket — well inside
#: both tiers on any plausible portfolio — so this is politeness and headroom,
#: not a workaround. It also means a capture running while somebody is loading
#: the dashboard does not push the two of them over the line together.
CALL_SPACING_SECONDS = 1.5

#: Longest we will sit on a throttle for one bucket before giving it up for this
#: run. The connector has already retried on the source's own schedule by the
#: time a `RateLimited` reaches us.
MAX_THROTTLE_WAIT_SECONDS = 30.0


def _capture_buckets(snapshot: PortfolioSnapshot) -> list[AssetType]:
    """The asset types worth asking for holdings on.

    Two filters, both of which save a call that could only ever come back empty
    or refused:

    - **non-empty only.** A bucket the snapshot values at zero (or does not
      value at all) has nothing to enumerate. Walking the full 16-member enum
      would spend most of a per-tool minute learning that.
    - **no `UNKNOWN`.** IND Money reports buckets its own holdings endpoint
      refuses — `US_STOCK_WALLET` is ~2.3% of the operator's portfolio — so the
      call is a guaranteed `UnsupportedAssetType`. Its value is already inside
      `total_value` and its payload is already in `snapshot_raw`; asking again
      would only burn budget. This is also precisely why the holdings rows do
      not sum to the total, and nothing here asserts that they do.
    """
    seen: dict[AssetType, None] = {}
    for slice_ in snapshot.by_asset_type:
        asset_type = slice_.asset_type
        if asset_type is None or asset_type is AssetType.UNKNOWN:
            continue
        if slice_.current_value is None or slice_.current_value <= 0:
            continue
        seen.setdefault(asset_type, None)
    return list(seen)


async def _ensure_user(session: AsyncSession, user_id: str) -> None:
    """Make sure a `users` row exists, idempotently.

    Done in the capture path rather than by hand because `snapshot_days.user_id`
    is a real FK: without the row the very first capture on a fresh database
    fails on a constraint, and "run this INSERT once before the cron starts" is
    a setup step somebody will forget at 23:45 on the night it matters.
    """
    await session.execute(
        pg_insert(User)
        .values(id=user_id, created_at=utcnow())
        .on_conflict_do_nothing(index_elements=[User.id])
    )


async def _day_exists(session: AsyncSession, user_id: str, day: date) -> bool:
    found = await session.scalar(
        select(SnapshotDay.id).where(
            SnapshotDay.user_id == user_id, SnapshotDay.captured_on == day
        )
    )
    return found is not None


def _holding_row(snapshot_id: int, holding: Holding) -> SnapshotHolding:
    return SnapshotHolding(
        snapshot_id=snapshot_id,
        source=holding.source,
        external_id=holding.external_id,
        asset_type=holding.asset_type.value,
        symbol=holding.symbol,
        isin=holding.isin,
        units=holding.units,
        avg_cost=holding.avg_cost,
        # None means unknown cost basis, and stays None. Storing 0 here would
        # resurrect the fabricated ±100% return M1 spent a card eliminating.
        invested_amount=holding.invested_amount,
        current_price=holding.current_price,
        current_value=holding.current_value,
        currency=holding.currency,
    )


async def capture_user(
    session: AsyncSession,
    user_id: str,
    *,
    connector: PortfolioConnector,
    now: Optional[datetime] = None,
    # `fx` and `call_spacing` resolve to the module globals at *call* time, not
    # at import time: bound as defaults they would be frozen into the function
    # object, and a caller (or a test) could never redirect the FX fetch or drop
    # the pacing without rewriting every call site.
    fx: Optional[FxFetcher] = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    call_spacing: Optional[float] = None,
) -> UserOutcome:
    """Capture one user's portfolio for the attributed day, or report why not.

    Idempotent per ``(user_id, captured_on)``, and when a day already exists the
    **first** capture wins. That is the deliberate choice: the primary run at
    23:45 IST is the one timed to sit after the NAV publish, so it is the truest
    reading of that day. A retry at 01:00 IST re-reading prices that have since
    moved would overwrite the good number with a worse one — the retry exists to
    rescue a day with *no* row, not to improve one that has one.

    The idempotency is enforced twice: a read first (cheap, and it avoids
    spending source calls on a day already captured) and the unique constraint
    second (correct, and it is what survives two runs racing).
    """
    now = now or _now_utc()
    fx = fx or fetch_usd_inr
    call_spacing = CALL_SPACING_SECONDS if call_spacing is None else call_spacing
    day = attributed_day(now)

    if await _day_exists(session, user_id, day):
        return UserOutcome(user_id=user_id, status=ALREADY_CAPTURED, captured_on=day)

    # ----------------------------------------------------------- acquisition
    raws: list[tuple[str, dict[str, Any]]] = []
    try:
        snapshot = await connector.fetch_snapshot(user_id)
    except NotLinked as exc:
        # A dead link is a fact about that user, not a failure of the run. It
        # must never abort the batch or turn the workflow red — otherwise one
        # lapsed account hides a real outage behind a permanent alarm.
        log.info("snapshot: skipping %s — link not usable (%s)", user_id, type(exc).__name__)
        return UserOutcome(
            user_id=user_id, status=SKIPPED, captured_on=day, reason="not_linked"
        )
    except PortfolioSourceError as exc:
        log.warning(
            "snapshot: %s failed on the source call (%s)", user_id, type(exc).__name__
        )
        return UserOutcome(
            user_id=user_id, status=FAILED, captured_on=day, reason="source_error"
        )

    raws.append((snapshot.source, {"kind": "snapshot", "asset_type": None, "payload": snapshot.raw}))

    holdings: list[Holding] = []
    failed: list[BucketFailure] = []
    for asset_type in _capture_buckets(snapshot):
        # Paced before the *first* bucket too: the snapshot call above already
        # spent a unit of the same global budget a moment ago.
        await sleep(call_spacing)
        rows, raw, failure = await _fetch_bucket(
            connector, user_id, asset_type, sleep=sleep
        )
        if failure is not None:
            failed.append(failure)
            continue
        holdings.extend(rows)
        raws.append(
            (snapshot.source, {"kind": "holdings", "asset_type": asset_type.value, "payload": raw})
        )

    rate = await fx()

    # ------------------------------------------------------------- persistence
    day_row = SnapshotDay(
        user_id=user_id,
        captured_on=day,
        total_value=snapshot.net_worth,
        currency=snapshot.currency,
        usd_inr_rate=rate,
        # NULL, not [], when nothing failed: a clean day leaves no marker, so
        # `buckets_failed IS NOT NULL` is the whole query for "which days are
        # incomplete".
        buckets_failed=[f.as_dict() for f in failed] or None,
        captured_at=now.astimezone(timezone.utc),
    )
    try:
        await _ensure_user(session, user_id)
        session.add(day_row)
        await session.flush()
        snapshot_id = day_row.id
        if snapshot_id is None:  # pragma: no cover - the flush above assigns it
            # A real check rather than an `assert`, which `python -O` removes.
            raise RuntimeError("snapshot_days row has no id after flush")
        for holding in holdings:
            session.add(_holding_row(snapshot_id, holding))
        for source, payload in raws:
            session.add(
                SnapshotRaw(
                    snapshot_id=snapshot_id,
                    source=source,
                    payload=payload,
                    captured_at=day_row.captured_at,
                )
            )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # **Only** a losing race on `(user_id, captured_on)` may be reported as
        # "already captured". Any other constraint failure — a holdings row that
        # violates a FK or a length, say — is a genuine bug, and swallowing it
        # here would file it under the one status nobody investigates: the run
        # would look like a free no-op while that day silently never got written.
        # Re-reading the day is driver-independent, unlike matching a constraint
        # name off an asyncpg exception.
        if not await _day_exists(session, user_id, day):
            log.exception("snapshot: %s failed to write %s", user_id, day)
            raise
        log.info("snapshot: %s already captured for %s (raced)", user_id, day)
        return UserOutcome(user_id=user_id, status=ALREADY_CAPTURED, captured_on=day)

    if failed:
        log.warning(
            "snapshot: %s captured for %s with %d unreadable bucket(s): %s",
            user_id,
            day,
            len(failed),
            ", ".join(f"{f.asset_type}({f.reason})" for f in failed),
        )
    return UserOutcome(
        user_id=user_id,
        status=CAPTURED,
        captured_on=day,
        holdings=len(holdings),
        buckets_failed=tuple(failed),
        fx_missing=rate is None,
    )


async def _fetch_bucket(
    connector: PortfolioConnector,
    user_id: str,
    asset_type: AssetType,
    *,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[list[Holding], dict[str, Any], Optional[BucketFailure]]:
    """One bucket's rows, honouring a throttle once before giving up.

    Returns ``(rows, raw, None)`` on success and ``([], {}, BucketFailure)``
    otherwise — the failure is a value rather than a flag because it is
    **persisted** onto the day (`snapshot_days.buckets_failed`), so the reason
    has to survive this function.

    The connector has already retried on the source's own ``retry_after`` by the
    time a :class:`RateLimited` escapes it, so this is a second, longer-horizon
    wait rather than a duplicate of that loop. Everything else is recorded as a
    failed bucket and the run continues: a snapshot missing one bucket's line
    items still carries the day's ``total_value``, which is what the history is
    drawn from, and a snapshot not written at all carries nothing at all.
    """
    for attempt in range(2):
        try:
            rows = await connector.fetch_holdings(user_id, asset_type)
        except RateLimited as exc:
            wait = min(float(exc.retry_after or 5.0), MAX_THROTTLE_WAIT_SECONDS)
            if attempt == 0 and wait > 0:
                log.info(
                    "snapshot: %s throttled on %s; waiting %.1fs",
                    user_id,
                    asset_type.value,
                    wait,
                )
                await sleep(wait)
                continue
            log.warning("snapshot: %s still throttled on %s", user_id, asset_type.value)
            return [], {}, BucketFailure(asset_type.value, BUCKET_THROTTLED)
        except UnsupportedAssetType:
            # The source reported a bucket it will not enumerate. Distinct from
            # an outage: no retry, ever, will produce those rows.
            log.warning(
                "snapshot: %s cannot enumerate %s at this source",
                user_id,
                asset_type.value,
            )
            return [], {}, BucketFailure(asset_type.value, BUCKET_UNSUPPORTED)
        except PortfolioSourceError as exc:
            log.warning(
                "snapshot: %s could not read %s (%s)",
                user_id,
                asset_type.value,
                type(exc).__name__,
            )
            return [], {}, BucketFailure(asset_type.value, BUCKET_SOURCE_ERROR)
        # `raw` is the source row as it arrived; the bucket's payload is the
        # list of them, which is what `snapshot_raw` stores for forensics.
        return rows, {"rows": [row.raw for row in rows]}, None
    return [], {}, BucketFailure(asset_type.value, BUCKET_THROTTLED)


async def capture_users(session: AsyncSession) -> list[str]:
    """Which users a batch run should try.

    Every user with a broker link. Before F3 the only such link was the
    process-wide one keyed on `"local"`, and this fell back to that constant so
    the nightly job had something to do; the fallback stays for exactly the
    window in which the operator's pre-F3 row is still keyed that way. Once
    adoption has moved it onto a Clerk id, the fallback stops firing because the
    query returns a real user — which is what makes the cutover a data
    migration rather than an edit to this function.
    """
    rows = await session.execute(select(distinct(BrokerLink.user_id)))
    linked = [row[0] for row in rows.all()]
    return linked or [LOCAL_USER_ID]


async def capture_all(
    session: AsyncSession,
    *,
    connector: Optional[PortfolioConnector] = None,
    connector_factory: Optional[Callable[[str], PortfolioConnector]] = None,
    user_ids: Optional[Sequence[str]] = None,
    now: Optional[datetime] = None,
    fx: Optional[FxFetcher] = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    call_spacing: Optional[float] = None,
) -> CaptureReport:
    """Capture every user, one at a time.

    **No user's failure ends the batch.** Each user is captured inside its own
    try/except and its own transaction, so a revoked link, a throttled source or
    a mapping error costs exactly that user's day and nothing else. The batch is
    serial rather than gathered because the rate limits are per *account* at the
    source and a fan-out would trip them the moment there is more than one user.

    ``connector_factory`` is how a real run gets **one connector per user** —
    the F3 shape, since a connector now carries a specific user's credentials.
    ``connector`` is the single-connector form, kept for the tests and callers
    that genuinely have one user in scope; passing it for a multi-user batch
    would (correctly) fail every user but the one it is bound to.
    """
    if connector is None and connector_factory is None:
        raise ValueError("capture_all needs a connector or a connector_factory")
    now = now or _now_utc()
    day = attributed_day(now)
    ids = list(user_ids) if user_ids is not None else await capture_users(session)

    outcomes: list[UserOutcome] = []
    for user_id in ids:
        try:
            outcome = await capture_user(
                session,
                user_id,
                connector=(
                    connector_factory(user_id) if connector_factory is not None
                    else connector
                ),
                now=now,
                fx=fx,
                sleep=sleep,
                call_spacing=call_spacing,
            )
        except Exception as exc:  # noqa: BLE001 - one user never aborts the batch
            log.exception("snapshot: unexpected failure capturing %s", user_id)
            with contextlib.suppress(Exception):
                await session.rollback()
            outcome = UserOutcome(
                user_id=user_id,
                status=FAILED,
                captured_on=day,
                reason=f"unexpected:{type(exc).__name__}",
            )
        outcomes.append(outcome)

    return CaptureReport(captured_on=day, outcomes=tuple(outcomes))


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #
RAW_RETENTION_DAYS = 90


async def prune_raw(session: AsyncSession, days: int = RAW_RETENTION_DAYS) -> int:
    """Delete `snapshot_raw` rows older than ``days``. Returns the row count.

    **Only the raw payloads.** Normalized rows and the daily totals are kept
    forever — they are the history, they are small, and they cannot be
    re-acquired. `snapshot_raw` is the forensic copy: useful for weeks while a
    mapping bug is fresh, unbounded growth after that.
    """
    if days < 1:
        raise ValueError("prune_raw refuses a window under one day")
    cutoff = _now_utc() - timedelta(days=days)
    result = await session.execute(
        delete(SnapshotRaw).where(SnapshotRaw.captured_at < cutoff)
    )
    await session.commit()
    return int(result.rowcount or 0)


# --------------------------------------------------------------------------- #
# Read side — what /portfolio/history and the staleness banner are built from
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HistoryPoint:
    captured_on: date
    total_value: Decimal


async def history_points(
    session: AsyncSession,
    user_id: str,
    *,
    days: int = 90,
    now: Optional[datetime] = None,
) -> list[HistoryPoint]:
    """The user's captured net worth over the last ``days`` attributed days."""
    now = now or _now_utc()
    since = attributed_day(now) - timedelta(days=days)
    rows = await session.execute(
        select(SnapshotDay.captured_on, SnapshotDay.total_value)
        .where(SnapshotDay.user_id == user_id, SnapshotDay.captured_on >= since)
        .order_by(SnapshotDay.captured_on)
    )
    return [HistoryPoint(captured_on=row[0], total_value=row[1]) for row in rows.all()]


async def last_captured_at(session: AsyncSession, user_id: str) -> Optional[datetime]:
    """When this user was last captured, whenever that was.

    Deliberately **not** windowed the way `history_points` is: the staleness
    banner's whole job is to notice a gap longer than the chart's window, and a
    query that forgot anything older than 90 days would go quiet exactly when
    the answer became interesting.
    """
    return await session.scalar(
        select(func.max(SnapshotDay.captured_at)).where(SnapshotDay.user_id == user_id)
    )


# --------------------------------------------------------------------------- #
# The third net — opportunistic capture
# --------------------------------------------------------------------------- #
_in_flight: set[str] = set()
_in_flight_lock = asyncio.Lock()
#: Strong references to background captures. `asyncio.create_task` only holds a
#: weak one, so without this a capture can be garbage-collected mid-flight —
#: which would look exactly like a source that silently stopped answering.
_background: set[asyncio.Task[Any]] = set()


def database_configured() -> bool:
    """Whether a Postgres URL is configured at all.

    Snapshots are additive to a deployment that has no database yet: the
    dashboard still reads live totals, the history is simply empty, and nothing
    here raises to say so.
    """
    return bool(os.environ.get(DATABASE_URL_ENV))


async def optional_session() -> AsyncGenerator[Optional[AsyncSession], None]:
    """FastAPI dependency yielding a session, or ``None`` when there is no DB.

    Used by the read-only portfolio routes, which must degrade to "no history"
    rather than 500 when `DATABASE_URL` is unset — the dashboard's live figures
    do not depend on Postgres and must not start doing so here.
    """
    if not database_configured():
        yield None
        return
    try:
        maker = get_sessionmaker()
    except Exception:  # noqa: BLE001 - a misconfigured URL is not a page failure
        log.warning("snapshot history unavailable: could not build a DB session")
        yield None
        return
    async with maker() as session:
        yield session


@contextlib.asynccontextmanager
async def single_flight(user_id: str) -> AsyncGenerator[bool, None]:
    """Yield ``True`` if this caller won the right to capture ``user_id``.

    Process-wide, not cluster-wide: two Space replicas could still both start a
    capture, and that is fine — the unique constraint on
    ``(user_id, captured_on)`` is the real guarantee and one of them simply
    loses. This lock's job is the cheaper one: stopping a dashboard that fires
    three requests on load from making three identical bursts of source calls
    against a per-minute rate limit.
    """
    async with _in_flight_lock:
        if user_id in _in_flight:
            yield False
            return
        _in_flight.add(user_id)
    try:
        yield True
    finally:
        async with _in_flight_lock:
            _in_flight.discard(user_id)


async def capture_if_missing(
    user_id: str,
    *,
    connector: PortfolioConnector,
    now: Optional[datetime] = None,
    session: Optional[AsyncSession] = None,
) -> Optional[UserOutcome]:
    """Capture the current attributed day if it has no row yet.

    The third net. The two scheduled runs are the plan; this is what covers the
    week GitHub quietly disables the workflow, or the night the Space refused to
    wake.

    ``session`` is optional because the two callers have genuinely different
    scopes: the awaited button press hands in the request's session, while the
    fire-and-forget background task has no request to borrow one from and must
    open (and close) its own — a request-scoped session is gone by the time that
    task runs.

    Returns ``None`` when it did not run at all (no database, or a capture for
    this user was already in flight).
    """
    if session is None and not database_configured():
        return None
    async with single_flight(user_id) as won:
        if not won:
            log.debug("opportunistic capture for %s already in flight", user_id)
            return None
        if session is not None:
            return await capture_user(session, user_id, connector=connector, now=now)
        maker = get_sessionmaker()
        async with maker() as owned:
            return await capture_user(owned, user_id, connector=connector, now=now)


def schedule_capture_if_missing(user_id: str, connector: PortfolioConnector) -> None:
    """Fire-and-forget :func:`capture_if_missing`. Never raises, never blocks.

    Called while serving `/portfolio/summary`. The reader asked to see their
    portfolio, not to wait ~10 seconds for a background job they did not
    request — so this returns immediately and the response goes out while the
    capture runs behind it.
    """

    async def _run() -> None:
        try:
            outcome = await capture_if_missing(user_id, connector=connector)
            if outcome and outcome.status == CAPTURED:
                log.info(
                    "opportunistic capture wrote %s for %s", outcome.captured_on, user_id
                )
        except Exception:  # noqa: BLE001 - a background net never breaks a page
            log.exception("opportunistic capture failed for %s", user_id)

    try:
        task = asyncio.create_task(_run())
    except RuntimeError:
        # No running loop (a sync test client, a script). Nothing to schedule.
        return
    _background.add(task)
    task.add_done_callback(_background.discard)


__all__ = [
    "ALREADY_CAPTURED",
    "ATTRIBUTION_CUTOFF_HOUR",
    "BUCKET_SOURCE_ERROR",
    "BUCKET_THROTTLED",
    "BUCKET_UNSUPPORTED",
    "CAPTURED",
    "FAILED",
    "BucketFailure",
    "FX_URL",
    "IST",
    "RAW_RETENTION_DAYS",
    "SKIPPED",
    "CaptureReport",
    "HistoryPoint",
    "UserOutcome",
    "attributed_day",
    "capture_all",
    "capture_if_missing",
    "capture_user",
    "capture_users",
    "database_configured",
    "fetch_usd_inr",
    "history_points",
    "last_captured_at",
    "last_expected_day",
    "optional_session",
    "prune_raw",
    "schedule_capture_if_missing",
    "single_flight",
]
