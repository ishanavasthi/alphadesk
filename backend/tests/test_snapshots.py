"""The capture service (card S1), against a real Postgres.

Every test here defends a property whose failure mode is **silent and
permanent**. A snapshot cannot be backfilled: the source answers "what is your
net worth now" and nothing else, so a day filed under the wrong date, dropped
because one user's link lapsed, or refused because a failed attempt left a
poison row is a day that no later run can recover.

SQLite is not an option for any of it — the cascade behaviour, the `timestamptz`
columns and the `UNIQUE (user_id, captured_on)` race are exactly the things it
would lie about.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SnapshotDay, SnapshotHolding, SnapshotRaw, User
from portfolio.connectors import PortfolioConnector, StubConnector
from portfolio.errors import (
    NotLinked,
    RateLimited,
    SourceUnavailable,
    UnsupportedAssetType,
    UserScopeError,
)
from portfolio.models import AssetType, Holding, LinkHealth, PortfolioSnapshot
from services import snapshots as svc

USER = "local"

#: 23:45 IST on 2026-08-16 — the primary run, expressed in UTC.
PRIMARY_RUN = datetime(2026, 8, 16, 18, 15, tzinfo=timezone.utc)
#: 01:00 IST on 2026-08-17 — the retry, which must file under 2026-08-16.
RETRY_RUN = datetime(2026, 8, 16, 19, 30, tzinfo=timezone.utc)

FIXED_RATE = Decimal("87.5")


async def _no_sleep(_seconds: float) -> None:
    """Pacing is real in production and pointless in a test."""


async def _fx_ok() -> Optional[Decimal]:
    return FIXED_RATE


async def _fx_down() -> Optional[Decimal]:
    """What `fetch_usd_inr` does on any failure: it degrades, it never raises."""
    return None


class ScriptedConnector(StubConnector):
    """The demo portfolio, with failures that can be scheduled per asset type.

    Subclasses the real stub rather than mocking the interface, so what is
    exercised is the same mapping and the same typed-error contract the
    production connectors are held to.
    """

    def __init__(
        self,
        *,
        snapshot_error: Optional[Exception] = None,
        holdings_errors: Optional[dict[AssetType, Exception]] = None,
        health: LinkHealth = LinkHealth.LINKED,
    ) -> None:
        super().__init__()
        self._snapshot_error = snapshot_error
        self._holdings_errors = dict(holdings_errors or {})
        self._health = health
        #: Every asset type this connector was asked to enumerate, in order.
        self.holdings_calls: list[AssetType] = []
        self.snapshot_calls = 0

    async def fetch_snapshot(self, user_id: str) -> PortfolioSnapshot:
        self.snapshot_calls += 1
        if self._snapshot_error is not None:
            raise self._snapshot_error
        return await super().fetch_snapshot(user_id)

    async def fetch_holdings(self, user_id: str, asset_type: AssetType) -> list[Holding]:
        self.holdings_calls.append(asset_type)
        error = self._holdings_errors.get(asset_type)
        if error is not None:
            raise error
        return await super().fetch_holdings(user_id, asset_type)

    async def link_health(self, user_id: str) -> LinkHealth:
        return self._health


async def _capture(
    session: AsyncSession,
    *,
    connector: Optional[StubConnector] = None,
    now: datetime = PRIMARY_RUN,
    fx: Any = _fx_ok,
    user_id: str = USER,
) -> svc.UserOutcome:
    return await svc.capture_user(
        session,
        user_id,
        connector=connector or ScriptedConnector(),
        now=now,
        fx=fx,
        sleep=_no_sleep,
        call_spacing=0,
    )


async def _days(session: AsyncSession) -> list[SnapshotDay]:
    rows = await session.execute(select(SnapshotDay).order_by(SnapshotDay.captured_on))
    return list(rows.scalars())


# --------------------------------------------------------------------------- #
# Attribution — the rule that decides which day a capture belongs to
# --------------------------------------------------------------------------- #
def test_attribution_cutoff_on_both_sides() -> None:
    """23:45 IST files under today; 01:00 IST files under yesterday.

    Both scheduled runs exist to fill the *same* day, and this is the only
    reason they can. Without the cutoff the retry would create tomorrow's row
    and the day it was rescuing would stay empty forever.
    """
    ist = svc.IST
    assert svc.attributed_day(datetime(2026, 8, 16, 23, 45, tzinfo=ist)) == date(2026, 8, 16)
    assert svc.attributed_day(datetime(2026, 8, 17, 1, 0, tzinfo=ist)) == date(2026, 8, 16)
    # The boundary itself, from both directions.
    assert svc.attributed_day(datetime(2026, 8, 17, 5, 59, tzinfo=ist)) == date(2026, 8, 16)
    assert svc.attributed_day(datetime(2026, 8, 17, 6, 0, tzinfo=ist)) == date(2026, 8, 17)


def test_attribution_is_ist_not_utc_and_not_server_local() -> None:
    """The zone itself is asserted, not just the schedule.

    Both scheduled runs are expressed in UTC because that is what the GitHub
    cron fires at — but note that neither of them discriminates on its own: a
    helper applying the same 06:00 cutoff to *UTC* would answer identically for
    both, because they fall the same side of both cutoffs.

    The last two assertions are the ones that actually pin the zone:

    - **02:00 UTC** is 07:30 IST, *past* the cutoff → the IST day. A UTC-based
      helper sees hour 2, applies the cutoff, and answers the day before.
    - **00:15 UTC** is 05:45 IST, *before* the cutoff → the previous day. A
      helper that took the plain UTC date with no cutoff answers the 16th.

    Between them they kill both wrong implementations.
    """
    assert svc.attributed_day(PRIMARY_RUN) == date(2026, 8, 16)
    assert svc.attributed_day(RETRY_RUN) == date(2026, 8, 16)
    # Late morning UTC is mid-afternoon IST: still the same day, no cutoff.
    assert svc.attributed_day(datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)) == date(
        2026, 8, 16
    )
    # 07:30 IST — past the cutoff. UTC + the same cutoff would say the 15th.
    assert svc.attributed_day(datetime(2026, 8, 16, 2, 0, tzinfo=timezone.utc)) == date(
        2026, 8, 16
    )
    # 05:45 IST — before it. A plain UTC date would say the 16th.
    assert svc.attributed_day(datetime(2026, 8, 16, 0, 15, tzinfo=timezone.utc)) == date(
        2026, 8, 15
    )


def test_attribution_refuses_a_naive_datetime() -> None:
    """A naive datetime would be attributed from whatever the server thinks the
    time is. That is the bug; guessing is not a degrade."""
    with pytest.raises(ValueError, match="timezone-aware"):
        svc.attributed_day(datetime(2026, 8, 16, 23, 45))


def test_last_expected_day_trails_by_one() -> None:
    """The banner's threshold: today's own capture has not necessarily run yet."""
    assert svc.last_expected_day(PRIMARY_RUN) == date(2026, 8, 15)
    assert svc.last_expected_day(RETRY_RUN) == date(2026, 8, 15)


# --------------------------------------------------------------------------- #
# Capture
# --------------------------------------------------------------------------- #
async def test_capture_writes_the_day_its_holdings_and_its_raw(
    db_session: AsyncSession,
) -> None:
    connector = ScriptedConnector()
    outcome = await _capture(db_session, connector=connector)

    assert outcome.status == svc.CAPTURED
    assert outcome.captured_on == date(2026, 8, 16)

    days = await _days(db_session)
    assert len(days) == 1
    day = days[0]
    # The vendor's own headline total, passed through — never a sum of the rows.
    snapshot = await StubConnector().fetch_snapshot(USER)
    assert day.total_value == snapshot.net_worth
    assert day.usd_inr_rate == FIXED_RATE
    assert day.currency == "INR"
    assert day.captured_at.tzinfo is not None

    holdings = (await db_session.execute(select(SnapshotHolding))).scalars().all()
    assert len(holdings) == outcome.holdings > 0
    assert {h.snapshot_id for h in holdings} == {day.id}

    raws = (await db_session.execute(select(SnapshotRaw))).scalars().all()
    kinds = [r.payload["kind"] for r in raws]
    assert kinds.count("snapshot") == 1
    assert kinds.count("holdings") == len(connector.holdings_calls)


async def test_capture_creates_the_user_row_it_needs(db_session: AsyncSession) -> None:
    """`snapshot_days.user_id` is a real FK, so the first capture on a fresh
    database has to make the row itself — a manual INSERT is a setup step
    somebody forgets on exactly the night it matters."""
    assert await db_session.get(User, USER) is None
    await _capture(db_session)
    assert await db_session.get(User, USER) is not None

    # And it is idempotent: a second capture (different day) must not collide.
    await _capture(db_session, now=PRIMARY_RUN + timedelta(days=1))
    assert len(await _days(db_session)) == 2


async def test_two_runs_on_the_same_attributed_day_make_one_row(
    db_session: AsyncSession,
) -> None:
    """The retry is a free no-op. This is the whole reason two runs are safe."""
    first = await _capture(db_session, now=PRIMARY_RUN)
    second = await _capture(db_session, now=RETRY_RUN)

    assert first.status == svc.CAPTURED
    assert second.status == svc.ALREADY_CAPTURED
    assert second.captured_on == first.captured_on == date(2026, 8, 16)
    assert len(await _days(db_session)) == 1


async def test_the_first_capture_of_a_day_wins(db_session: AsyncSession) -> None:
    """The 23:45 run sits after the NAV publish and is the truest reading of the
    day; a 01:00 retry re-reading moved prices must not overwrite it."""
    await _capture(db_session, now=PRIMARY_RUN, fx=_fx_ok)

    async def _different_rate() -> Optional[Decimal]:
        return Decimal("99.99")

    await _capture(db_session, now=RETRY_RUN, fx=_different_rate)

    days = await _days(db_session)
    assert len(days) == 1
    assert days[0].usd_inr_rate == FIXED_RATE


async def test_a_second_run_does_not_spend_source_calls(
    db_session: AsyncSession,
) -> None:
    """Idempotency is checked *before* the source is touched: the retry costs
    nothing against a per-minute rate limit."""
    await _capture(db_session, now=PRIMARY_RUN)
    connector = ScriptedConnector()
    await _capture(db_session, connector=connector, now=RETRY_RUN)
    assert connector.snapshot_calls == 0
    assert connector.holdings_calls == []


async def test_only_non_empty_buckets_are_enumerated(
    db_session: AsyncSession,
) -> None:
    """Never the full 16, and never the un-enumerable UNKNOWN bucket.

    Walking the enum would spend most of a per-tool minute learning that 11 of
    16 are empty (C2), and `UNKNOWN` is a guaranteed `UnsupportedAssetType` — the
    source reports buckets its own holdings endpoint refuses. That bucket's value
    is already inside `total_value`, which is precisely why the rows below never
    sum to it.
    """
    connector = ScriptedConnector()
    await _capture(db_session, connector=connector)

    asked = connector.holdings_calls
    assert asked, "at least one bucket should have been read"
    assert len(asked) < len(AssetType.queryable())
    assert AssetType.UNKNOWN not in asked
    assert len(set(asked)) == len(asked), "no bucket asked for twice"

    snapshot = await StubConnector().fetch_snapshot(USER)
    non_empty = {
        s.asset_type
        for s in snapshot.by_asset_type
        if s.asset_type not in (None, AssetType.UNKNOWN) and s.current_value > 0
    }
    assert set(asked) == non_empty


async def test_totals_are_not_asserted_against_the_holdings_sum(
    db_session: AsyncSession,
) -> None:
    """They do not reconcile, by construction (M1 §5), and nothing here pretends
    otherwise — a future 'sanity check' that added equality would fail here."""
    await _capture(db_session)
    day = (await _days(db_session))[0]
    total_rows = await db_session.scalar(
        select(func.coalesce(func.sum(SnapshotHolding.current_value), 0)).where(
            SnapshotHolding.snapshot_id == day.id
        )
    )
    assert total_rows != day.total_value


async def test_an_unreadable_bucket_still_writes_the_day(
    db_session: AsyncSession,
) -> None:
    """A partial snapshot beats no snapshot. `total_value` — the figure the whole
    history is drawn from — comes off the snapshot call, not the buckets."""
    connector = ScriptedConnector(
        holdings_errors={AssetType.MF: SourceUnavailable("mf: transport blew up")}
    )
    outcome = await _capture(db_session, connector=connector)

    assert outcome.status == svc.CAPTURED
    assert outcome.buckets_failed == (
        svc.BucketFailure("MF", svc.BUCKET_SOURCE_ERROR),
    )
    assert len(await _days(db_session)) == 1
    stored = (await db_session.execute(select(SnapshotHolding.asset_type))).scalars().all()
    assert "MF" not in stored
    assert stored, "the other buckets still landed"


async def test_a_partial_capture_leaves_queryable_evidence(
    db_session: AsyncSession,
) -> None:
    """**The partiality has to outlive the response body.**

    Without a stored marker, this day and a day where the user genuinely held no
    mutual funds are byte-identical in the database — the rows are absent either
    way. "You held nothing in that bucket" would then be a false statement about
    somebody's money that no later query could correct, because the source is
    point-in-time and cannot be re-asked.

    It lives on `snapshot_days`, not in `snapshot_raw`, because raw payloads are
    pruned at 90 days and the day is kept forever.
    """
    connector = ScriptedConnector(
        holdings_errors={
            AssetType.MF: SourceUnavailable("mf: transport blew up"),
            AssetType.FD: UnsupportedAssetType("fd: nope"),
        }
    )
    await _capture(db_session, connector=connector)

    day = (await _days(db_session))[0]
    assert day.buckets_failed is not None
    assert {(f["asset_type"], f["reason"]) for f in day.buckets_failed} == {
        ("MF", svc.BUCKET_SOURCE_ERROR),
        ("FD", svc.BUCKET_UNSUPPORTED),
    }

    # And it is queryable as a set: "which days are incomplete" is one predicate.
    incomplete = await db_session.scalar(
        select(func.count())
        .select_from(SnapshotDay)
        .where(SnapshotDay.buckets_failed.is_not(None))
    )
    assert incomplete == 1


async def test_a_clean_capture_leaves_no_marker(db_session: AsyncSession) -> None:
    """NULL, not `[]`. A clean day carries no marker at all, so
    `buckets_failed IS NOT NULL` is the whole query for "incomplete"."""
    await _capture(db_session)
    day = (await _days(db_session))[0]
    assert day.buckets_failed is None

    incomplete = await db_session.scalar(
        select(func.count())
        .select_from(SnapshotDay)
        .where(SnapshotDay.buckets_failed.is_not(None))
    )
    assert incomplete == 0


async def test_a_throttled_bucket_is_retried_once_then_given_up(
    db_session: AsyncSession,
) -> None:
    """The connector has already retried on the source's own schedule by the time
    a `RateLimited` reaches us, so this is one longer wait, not a hot loop."""
    # `RateLimited` is a source-neutral carrier: the code string is whatever the
    # connector read off its own throttle body, and nothing above the connector
    # boundary is allowed to know what any vendor calls it.
    throttle = RateLimited("t", "throttled", retry_after=1.0, scope="tool")
    connector = ScriptedConnector(holdings_errors={AssetType.MF: throttle})
    waits: list[float] = []

    async def _record(seconds: float) -> None:
        waits.append(seconds)

    outcome = await svc.capture_user(
        db_session,
        USER,
        connector=connector,
        now=PRIMARY_RUN,
        fx=_fx_ok,
        sleep=_record,
        call_spacing=0,
    )

    assert outcome.status == svc.CAPTURED
    assert outcome.buckets_failed == (svc.BucketFailure("MF", svc.BUCKET_THROTTLED),)
    assert connector.holdings_calls.count(AssetType.MF) == 2
    assert 1.0 in waits
    # A throttle and an outage are different diagnoses and are stored as such:
    # one says "ask again tomorrow", the other says "something is broken".
    day = (await _days(db_session))[0]
    assert day.buckets_failed == [{"asset_type": "MF", "reason": svc.BUCKET_THROTTLED}]


async def test_an_unsupported_bucket_is_not_fatal(db_session: AsyncSession) -> None:
    """If a source ever reports a bucket it refuses to enumerate under a real
    asset type, that is a gap in the rows, not a lost day."""
    connector = ScriptedConnector(
        holdings_errors={AssetType.FD: UnsupportedAssetType("fd: nope")}
    )
    outcome = await _capture(db_session, connector=connector)
    assert outcome.status == svc.CAPTURED
    assert outcome.buckets_failed == (
        svc.BucketFailure("FD", svc.BUCKET_UNSUPPORTED),
    )


async def test_a_dead_link_is_skipped_not_failed(db_session: AsyncSession) -> None:
    """A lapsed account is a fact about that user, not an outage. Reporting it as
    an error would leave the workflow permanently red and hide a real failure."""
    connector = ScriptedConnector(snapshot_error=NotLinked("no credential"))
    outcome = await _capture(db_session, connector=connector)

    assert outcome.status == svc.SKIPPED
    assert outcome.reason == "not_linked"
    assert await _days(db_session) == []


async def test_a_source_outage_is_an_error_and_writes_nothing(
    db_session: AsyncSession,
) -> None:
    connector = ScriptedConnector(snapshot_error=SourceUnavailable("502 from upstream"))
    outcome = await _capture(db_session, connector=connector)

    assert outcome.status == svc.FAILED
    assert outcome.reason == "source_error"
    assert await _days(db_session) == []


async def test_a_failed_attempt_leaves_no_row_for_the_retry_to_collide_with(
    db_session: AsyncSession,
) -> None:
    """The 502-then-success case.

    The workflow's whole retry strategy rests on this: a first attempt that dies
    against a sleeping Space must not leave a partial row, because idempotency
    would then refuse to replace it and the day would be lost to a *successful*
    retry. Attempt one fails, attempt two on the same attributed day writes the
    day in full.
    """
    failing = ScriptedConnector(snapshot_error=SourceUnavailable("502 Bad Gateway"))
    first = await _capture(db_session, connector=failing, now=PRIMARY_RUN)
    assert first.status == svc.FAILED
    assert await _days(db_session) == []

    second = await _capture(db_session, connector=ScriptedConnector(), now=RETRY_RUN)
    assert second.status == svc.CAPTURED
    days = await _days(db_session)
    assert [d.captured_on for d in days] == [date(2026, 8, 16)]
    assert second.holdings > 0


async def test_a_non_unique_constraint_failure_is_not_reported_as_already_captured(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a losing race on `(user_id, captured_on)` may report `already_captured`.

    Every other `IntegrityError` is a bug, and reporting it as "already captured"
    would file it under the one status nobody investigates: the run looks like a
    free no-op while that day silently never got written — and a day cannot be
    written later.

    Forced with a holdings row pointing at a snapshot id that does not exist, so
    the failing constraint is a foreign key rather than the unique index.
    """
    real_holding_row = svc._holding_row

    def _broken(snapshot_id: int, holding: Holding) -> SnapshotHolding:
        row = real_holding_row(snapshot_id, holding)
        row.snapshot_id = 10_000_000  # no such snapshot_days row
        return row

    monkeypatch.setattr(svc, "_holding_row", _broken)

    with pytest.raises(IntegrityError):
        await _capture(db_session)

    await db_session.rollback()
    assert await _days(db_session) == [], "nothing partial was left behind"


async def test_the_batch_records_that_failure_instead_of_swallowing_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """...and `capture_all` turns it into a visible error, not a silent skip."""
    real_holding_row = svc._holding_row

    def _broken(snapshot_id: int, holding: Holding) -> SnapshotHolding:
        row = real_holding_row(snapshot_id, holding)
        row.snapshot_id = 10_000_000
        return row

    monkeypatch.setattr(svc, "_holding_row", _broken)

    report = await svc.capture_all(
        db_session,
        connector=ScriptedConnector(),
        user_ids=[USER],
        now=PRIMARY_RUN,
        fx=_fx_ok,
        sleep=_no_sleep,
        call_spacing=0,
    )
    assert report.errors == 1
    assert report.skipped == 0
    assert report.outcomes[0].reason == "unexpected:IntegrityError"


async def test_fx_failure_stores_null_and_still_writes_the_row(
    db_session: AsyncSession,
) -> None:
    """The rate is display math; the snapshot is data that cannot be re-acquired.
    Losing the second to save the first would be an obviously bad trade."""
    outcome = await _capture(db_session, fx=_fx_down)

    assert outcome.status == svc.CAPTURED
    assert outcome.fx_missing is True
    day = (await _days(db_session))[0]
    assert day.usd_inr_rate is None
    assert day.total_value > 0


async def test_fetch_usd_inr_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever goes wrong — DNS, timeout, a reshaped body — the answer is None.

    Driven through the real function with a broken transport rather than by
    trusting the `except` clause to be reachable.
    """
    import httpx

    class _Boom:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_Boom":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str) -> Any:
            raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    assert await svc.fetch_usd_inr() is None


# --------------------------------------------------------------------------- #
# The batch
# --------------------------------------------------------------------------- #
async def test_one_users_dead_link_never_aborts_the_batch(
    db_session: AsyncSession,
) -> None:
    """The headline batch property. A revoked account is captured as `skipped`
    and everyone after it still gets their day."""

    class PerUser(ScriptedConnector):
        async def fetch_snapshot(self, user_id: str) -> PortfolioSnapshot:
            if user_id == "revoked":
                raise NotLinked("the source rejected this grant")
            if user_id == "broken":
                raise SourceUnavailable("upstream 500")
            return await StubConnector().fetch_snapshot(USER)

        async def fetch_holdings(
            self, user_id: str, asset_type: AssetType
        ) -> list[Holding]:
            return await StubConnector().fetch_holdings(USER, asset_type)

    report = await svc.capture_all(
        db_session,
        connector=PerUser(),
        user_ids=["revoked", "alice", "broken", "bob"],
        now=PRIMARY_RUN,
        fx=_fx_ok,
        sleep=_no_sleep,
        call_spacing=0,
    )

    assert report.captured_on == date(2026, 8, 16)
    assert report.users_captured == 2
    assert report.skipped == 1
    assert report.errors == 1
    captured = {d.user_id for d in await _days(db_session)}
    assert captured == {"alice", "bob"}

    body = report.as_dict()
    assert body["captured_on"] == "2026-08-16"
    assert {d["user_id"] for d in body["details"]} == {"revoked", "alice", "broken", "bob"}
    # Reasons are our own fixed strings, never the source's message text.
    assert all(
        d["reason"] in (None, "not_linked", "source_error") for d in body["details"]
    )


async def test_capture_users_defaults_to_the_single_local_user(
    db_session: AsyncSession,
) -> None:
    assert await svc.capture_users(db_session) == ["local"]


# --------------------------------------------------------------------------- #
# Retention and cascades
# --------------------------------------------------------------------------- #
async def test_prune_deletes_only_old_raw(db_session: AsyncSession) -> None:
    await _capture(db_session, now=PRIMARY_RUN)
    await _capture(db_session, now=PRIMARY_RUN - timedelta(days=200))

    day_count = await db_session.scalar(select(func.count()).select_from(SnapshotDay))
    holding_count = await db_session.scalar(
        select(func.count()).select_from(SnapshotHolding)
    )
    raw_count = await db_session.scalar(select(func.count()).select_from(SnapshotRaw))
    assert day_count == 2 and holding_count > 0 and raw_count > 0

    # Age the older day's raw payloads past the window.
    old_day = (await _days(db_session))[0]
    await db_session.execute(
        text("UPDATE snapshot_raw SET captured_at = now() - interval '200 days' "
             "WHERE snapshot_id = :sid").bindparams(sid=old_day.id)
    )
    await db_session.commit()

    deleted = await svc.prune_raw(db_session, days=90)
    assert deleted > 0

    assert await db_session.scalar(select(func.count()).select_from(SnapshotDay)) == day_count
    assert (
        await db_session.scalar(select(func.count()).select_from(SnapshotHolding))
        == holding_count
    )
    remaining = (await db_session.execute(select(SnapshotRaw.snapshot_id))).scalars().all()
    assert remaining and old_day.id not in remaining


async def test_prune_refuses_a_zero_day_window(db_session: AsyncSession) -> None:
    """`prune_raw(session, days=0)` would delete everything captured tonight."""
    with pytest.raises(ValueError):
        await svc.prune_raw(db_session, days=0)


async def test_deleting_the_user_cascades_to_days_holdings_and_raw(
    db_session: AsyncSession,
) -> None:
    """Raw SQL on purpose: L1's "delete my data" must work from psql or a
    migration, not only through the ORM. An unstated cascade on `snapshot_days`
    would either fail on the FK or leave a person's entire net-worth history
    behind after they asked for it to be erased."""
    await _capture(db_session)
    assert await db_session.scalar(select(func.count()).select_from(SnapshotDay)) == 1

    await db_session.execute(text("DELETE FROM users WHERE id = :uid").bindparams(uid=USER))
    await db_session.commit()

    for model in (SnapshotDay, SnapshotHolding, SnapshotRaw):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


# --------------------------------------------------------------------------- #
# Read side
# --------------------------------------------------------------------------- #
async def test_history_points_are_ordered_and_windowed(
    db_session: AsyncSession,
) -> None:
    for offset in (0, 1, 5, 200):
        await _capture(db_session, now=PRIMARY_RUN - timedelta(days=offset))

    points = await svc.history_points(db_session, USER, days=90, now=PRIMARY_RUN)
    days = [p.captured_on for p in points]
    assert days == sorted(days)
    assert len(days) == 3, "the 200-day-old capture is outside a 90-day window"
    assert all(isinstance(p.total_value, Decimal) for p in points)


async def test_last_captured_at_is_not_windowed(db_session: AsyncSession) -> None:
    """The banner has to notice a gap *longer* than the chart's window — a
    windowed query would go quiet exactly when the answer became interesting."""
    await _capture(db_session, now=PRIMARY_RUN - timedelta(days=400))
    stamp = await svc.last_captured_at(db_session, USER)
    assert stamp is not None
    assert (await svc.history_points(db_session, USER, days=90, now=PRIMARY_RUN)) == []


async def test_last_captured_at_is_none_for_an_uncaptured_user(
    db_session: AsyncSession,
) -> None:
    assert await svc.last_captured_at(db_session, "nobody") is None


# --------------------------------------------------------------------------- #
# The third net
# --------------------------------------------------------------------------- #
async def test_single_flight_admits_one_caller_at_a_time() -> None:
    async with svc.single_flight(USER) as first:
        assert first is True
        async with svc.single_flight(USER) as second:
            assert second is False
        # A different user is unaffected.
        async with svc.single_flight("someone-else") as other:
            assert other is True
    # Released on exit.
    async with svc.single_flight(USER) as again:
        assert again is True


async def test_single_flight_releases_after_a_failure() -> None:
    """A capture that raises must not wedge the guard shut until restart."""
    with pytest.raises(RuntimeError):
        async with svc.single_flight(USER) as won:
            assert won is True
            raise RuntimeError("boom")
    async with svc.single_flight(USER) as again:
        assert again is True


async def test_the_batch_builds_one_connector_per_user(
    db_session: AsyncSession,
) -> None:
    """**The seam the M1 singleton used to occupy.**

    `capture_all` is the one caller that iterates users, so it is the one place
    where "the connector is per user" can silently stop being true — a cron job
    that binds every user to the operator's credential writes one person's
    holdings into everybody's history, and nothing else in the system would
    notice. So the factory records the id it was asked for, and each connector
    it returns **refuses** any other user, which is what makes
    `connector_factory("local")` (or any other constant) fail here rather than
    quietly pass.
    """
    asked: list[str] = []

    class BoundConnector(ScriptedConnector):
        """Exactly what `IndMoneyConnector` is: usable by one user only."""

        def __init__(self, user_id: str) -> None:
            super().__init__()
            self._bound = user_id

        def _check(self, user_id: str) -> None:
            if user_id != self._bound:
                raise UserScopeError(
                    f"connector bound to {self._bound!r} cannot serve {user_id!r}"
                )

        async def fetch_snapshot(self, user_id: str) -> PortfolioSnapshot:
            self._check(user_id)
            return await StubConnector().fetch_snapshot(USER)

        async def fetch_holdings(
            self, user_id: str, asset_type: AssetType
        ) -> list[Holding]:
            self._check(user_id)
            return await StubConnector().fetch_holdings(USER, asset_type)

    def factory(user_id: str) -> PortfolioConnector:
        asked.append(user_id)
        return BoundConnector(user_id)

    report = await svc.capture_all(
        db_session,
        connector_factory=factory,
        user_ids=["alice", "bob"],
        now=PRIMARY_RUN,
        fx=_fx_ok,
        sleep=_no_sleep,
        call_spacing=0,
    )

    assert asked == ["alice", "bob"], "one connector per user, in order"
    assert report.users_captured == 2
    assert report.errors == 0
    assert {d.user_id for d in await _days(db_session)} == {"alice", "bob"}


async def test_the_batch_refuses_to_run_with_no_connector_at_all(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError):
        await svc.capture_all(db_session, user_ids=["alice"], now=PRIMARY_RUN)
