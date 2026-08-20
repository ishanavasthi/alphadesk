"""Card B8 — top movers over a user-chosen window, read from captured snapshots.

Two halves, and the split matters:

- the **service** tests build days and holdings by hand against the real
  migrated database, because every rule this card exists for is a rule about
  which rows end up in which list;
- the **route** tests drive the ASGI app, because the contract the frontend
  codes against includes the identity gate and the no-database degradation, and
  neither of those is visible from the service.

Every assertion below is a sentence about someone's money. A percentage taken
from `current_value` would report a top-up as a rally; a throttled bucket read
as an empty one would report a holding as sold; a position seen on one day only
rendered as ±100% would invent a return. Those three are the file's spine.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.main import app
from api.routes.portfolio import connector_factory, connector_for_request
from db.models import SnapshotDay, SnapshotHolding, SnapshotRaw, User, utcnow
from db.session import async_session
from portfolio.connectors import StubConnector
from portfolio.models import LinkHealth
from services import snapshots as svc

USER = "movers-user"
DAY_A = date(2026, 8, 16)
DAY_B = date(2026, 8, 20)


# --------------------------------------------------------------------------- #
# Fixture helpers — hand-built days, so each test states exactly its own case
# --------------------------------------------------------------------------- #
async def _day(
    session: AsyncSession,
    captured_on: date,
    *,
    user_id: str = USER,
    total: str = "1000",
    buckets_failed: Optional[list[dict[str, str]]] = None,
) -> int:
    await session.execute(
        text("INSERT INTO users (id, created_at) VALUES (:i, :t) ON CONFLICT DO NOTHING"),
        {"i": user_id, "t": utcnow()},
    )
    row = SnapshotDay(
        user_id=user_id,
        captured_on=captured_on,
        total_value=Decimal(total),
        usd_inr_rate=None,
        buckets_failed=buckets_failed,
        captured_at=datetime(
            captured_on.year, captured_on.month, captured_on.day, 18, 15, tzinfo=timezone.utc
        ),
    )
    session.add(row)
    await session.flush()
    assert row.id is not None
    return row.id


def _holding(
    snapshot_id: int,
    external_id: str,
    *,
    asset_type: str = "EQUITY",
    name: Optional[str] = None,
    units: Optional[str] = None,
    price: Optional[str] = None,
    value: str = "0",
) -> SnapshotHolding:
    return SnapshotHolding(
        snapshot_id=snapshot_id,
        source="ind_money",
        external_id=external_id,
        asset_type=asset_type,
        name=name,
        units=None if units is None else Decimal(units),
        current_price=None if price is None else Decimal(price),
        current_value=Decimal(value),
    )


def _by_id(rows: Any) -> dict[str, Any]:
    return {row.external_id: row for row in rows}


# --------------------------------------------------------------------------- #
# The honest-data core
# --------------------------------------------------------------------------- #
async def test_price_basis_ranks_on_price_not_value(db_session: AsyncSession) -> None:
    """A top-up must not read as a rally.

    `TOPUP` doubles in *value* while its price falls 10%; `MOVER` gains 20% on
    price with no unit change. A ranking taken from `current_value` would put
    the top-up first and call it the day's best performer, which is a false
    statement about a market that went the other way.
    """
    a = await _day(db_session, DAY_A)
    b = await _day(db_session, DAY_B)
    db_session.add_all(
        [
            _holding(a, "EQUITY:TOPUP", units="10", price="100", value="1000"),
            _holding(b, "EQUITY:TOPUP", units="22", price="90", value="1980"),
            _holding(a, "EQUITY:MOVER", units="5", price="200", value="1000"),
            _holding(b, "EQUITY:MOVER", units="5", price="240", value="1200"),
        ]
    )
    await db_session.commit()

    report = await svc.movers_report(db_session, USER, from_day=DAY_A, to_day=DAY_B)

    assert [r.external_id for r in report.gainers] == ["EQUITY:MOVER"]
    assert report.gainers[0].change_pct == Decimal("20.00")
    assert [r.external_id for r in report.losers] == ["EQUITY:TOPUP"]
    topup = report.losers[0]
    assert topup.change_pct == Decimal("-10.00")
    # The rupee column still tells the truth about the money — it is the
    # *percentage* that must never come off the value.
    assert topup.change_abs == Decimal("980")


async def test_balance_rows_are_flows_never_movers(db_session: AsyncSession) -> None:
    """A deposit is money moved, not market movement.

    The savings account here is by far the largest rupee change in the window.
    It must still never appear in `gainers`, and it must carry no percentage —
    there is no price to take one from.
    """
    a = await _day(db_session, DAY_A)
    b = await _day(db_session, DAY_B)
    db_session.add_all(
        [
            _holding(a, "SA:BANK1", asset_type="SA", value="10000"),
            _holding(b, "SA:BANK1", asset_type="SA", value="26500"),
            _holding(a, "EQUITY:MOVER", units="5", price="200", value="1000"),
            _holding(b, "EQUITY:MOVER", units="5", price="202", value="1010"),
        ]
    )
    await db_session.commit()

    report = await svc.movers_report(db_session, USER, from_day=DAY_A, to_day=DAY_B)

    ranked = {r.external_id for r in report.gainers} | {r.external_id for r in report.losers}
    assert "SA:BANK1" not in ranked
    assert [r.external_id for r in report.flows] == ["SA:BANK1"]
    flow = report.flows[0]
    assert flow.basis == svc.BASIS_BALANCE
    assert flow.change_pct is None
    assert flow.change_abs == Decimal("16500")


async def test_opened_and_closed_are_never_plus_or_minus_100(
    db_session: AsyncSession,
) -> None:
    """A position seen once is not a 100% return in either direction.

    Includes the honest-empty bucket case from the contract: FD returned
    ``{"rows": []}`` on the later day with `buckets_failed` NULL, so the deposit
    really is gone — reported as *closed*, not as -100%.
    """
    a = await _day(db_session, DAY_A)
    b = await _day(db_session, DAY_B)
    db_session.add_all(
        [
            _holding(b, "EQUITY:NEW", units="3", price="50", value="150"),
            _holding(a, "FD:OLD", asset_type="FD", value="5000"),
        ]
    )
    await db_session.commit()

    report = await svc.movers_report(db_session, USER, from_day=DAY_A, to_day=DAY_B)

    assert [r.external_id for r in report.opened] == ["EQUITY:NEW"]
    assert [r.external_id for r in report.closed] == ["FD:OLD"]
    for row in (*report.opened, *report.closed):
        assert row.change_pct is None
        assert row.change_abs is None
    assert report.gainers == () and report.losers == () and report.flows == ()


async def test_failed_bucket_is_unknown_not_empty(db_session: AsyncSession) -> None:
    """A bucket that could not be read is excluded from every list.

    The MF rows exist on the earlier day and are missing on the later one only
    because the bucket was throttled. Listing them as `closed` would tell the
    reader they sold funds they still hold.
    """
    a = await _day(db_session, DAY_A)
    b = await _day(
        db_session, DAY_B, buckets_failed=[{"asset_type": "MF", "reason": "throttled"}]
    )
    db_session.add_all(
        [
            _holding(a, "MF:FUND1", asset_type="MF", units="10", price="20", value="200"),
            _holding(a, "EQUITY:MOVER", units="5", price="200", value="1000"),
            _holding(b, "EQUITY:MOVER", units="5", price="210", value="1050"),
        ]
    )
    await db_session.commit()

    report = await svc.movers_report(db_session, USER, from_day=DAY_A, to_day=DAY_B)

    every = (*report.gainers, *report.losers, *report.flows, *report.opened, *report.closed)
    assert all(r.asset_type != "MF" for r in every)
    assert report.excluded == (
        {"asset_type": "MF", "reason": f"bucket failed on {DAY_B.isoformat()}"},
    )
    assert [r.external_id for r in report.gainers] == ["EQUITY:MOVER"]


async def test_window_snaps_to_captured_days_and_says_so(
    db_session: AsyncSession,
) -> None:
    """Snap inwards, never widen, never interpolate — and admit it in `note`."""
    a = await _day(db_session, DAY_A)
    b = await _day(db_session, DAY_B)
    db_session.add_all(
        [
            _holding(a, "EQUITY:MOVER", units="5", price="200", value="1000"),
            _holding(b, "EQUITY:MOVER", units="5", price="220", value="1100"),
        ]
    )
    await db_session.commit()

    report = await svc.movers_report(
        db_session, USER, from_day=date(2026, 8, 10), to_day=date(2026, 8, 25)
    )

    assert (report.requested_from, report.requested_to) == (date(2026, 8, 10), date(2026, 8, 25))
    assert (report.compared_from, report.compared_to) == (DAY_A, DAY_B)
    assert report.note is not None
    assert DAY_A.isoformat() in report.note and DAY_B.isoformat() in report.note

    # An exact hit on both ends has nothing to confess.
    exact = await svc.movers_report(db_session, USER, from_day=DAY_A, to_day=DAY_B)
    assert exact.note is None


async def test_single_captured_day_in_window_is_empty_with_a_note(
    db_session: AsyncSession,
) -> None:
    """One day is not a comparison. Never widen the window to manufacture one."""
    a = await _day(db_session, DAY_A)
    db_session.add(_holding(a, "EQUITY:MOVER", units="5", price="200", value="1000"))
    await db_session.commit()

    report = await svc.movers_report(
        db_session, USER, from_day=DAY_A, to_day=date(2026, 8, 18)
    )

    assert report.compared_from == report.compared_to == DAY_A
    assert report.gainers == () and report.losers == ()
    assert report.note is not None


async def test_join_is_on_identity_pair_not_symbol(db_session: AsyncSession) -> None:
    """Two rows with NULL `symbol` are two holdings, not one.

    Every IND Money mutual-fund and savings row has a NULL symbol, so a join on
    it would merge the whole bucket into a single line.
    """
    a = await _day(db_session, DAY_A)
    b = await _day(db_session, DAY_B)
    db_session.add_all(
        [
            _holding(a, "MF:F1", asset_type="MF", units="10", price="20", value="200"),
            _holding(b, "MF:F1", asset_type="MF", units="10", price="22", value="220"),
            _holding(a, "MF:F2", asset_type="MF", units="10", price="30", value="300"),
            _holding(b, "MF:F2", asset_type="MF", units="10", price="27", value="270"),
        ]
    )
    await db_session.commit()

    report = await svc.movers_report(db_session, USER, from_day=DAY_A, to_day=DAY_B)

    assert [r.external_id for r in report.gainers] == ["MF:F1"]
    assert [r.external_id for r in report.losers] == ["MF:F2"]


async def test_name_comes_from_the_column_and_falls_back_to_raw(
    db_session: AsyncSession,
) -> None:
    """Post-B8 rows carry their own name; pre-B8 rows borrow one from `snapshot_raw`.

    And a row whose raw payload has been pruned stays nameless rather than
    being guessed at from a neighbouring row.
    """
    a = await _day(db_session, DAY_A)
    b = await _day(db_session, DAY_B)
    db_session.add_all(
        [
            _holding(a, "EQUITY:NAMED", units="1", price="10", value="10"),
            _holding(b, "EQUITY:NAMED", name="Named Co", units="1", price="11", value="11"),
            _holding(a, "EQUITY:LEGACY", units="1", price="10", value="10"),
            _holding(b, "EQUITY:LEGACY", units="1", price="12", value="12"),
            _holding(a, "EQUITY:PRUNED", units="1", price="10", value="10"),
            _holding(b, "EQUITY:PRUNED", units="1", price="13", value="13"),
        ]
    )
    db_session.add(
        SnapshotRaw(
            snapshot_id=b,
            source="ind_money",
            payload={
                "kind": "holdings",
                "asset_type": "EQUITY",
                "payload": {"rows": [{"investment_code": "LEGACY", "investment": "Legacy Ltd"}]},
            },
        )
    )
    await db_session.commit()

    report = await svc.movers_report(db_session, USER, from_day=DAY_A, to_day=DAY_B)
    names = {r.external_id: r.name for r in report.gainers}

    assert names["EQUITY:NAMED"] == "Named Co"
    assert names["EQUITY:LEGACY"] == "Legacy Ltd"
    assert names["EQUITY:PRUNED"] is None


async def test_limit_caps_each_side_independently(db_session: AsyncSession) -> None:
    a = await _day(db_session, DAY_A)
    b = await _day(db_session, DAY_B)
    for i in range(4):
        db_session.add(_holding(a, f"EQUITY:UP{i}", units="1", price="100", value="100"))
        db_session.add(
            _holding(b, f"EQUITY:UP{i}", units="1", price=str(101 + i), value=str(101 + i))
        )
        db_session.add(_holding(a, f"EQUITY:DN{i}", units="1", price="100", value="100"))
        db_session.add(
            _holding(b, f"EQUITY:DN{i}", units="1", price=str(99 - i), value=str(99 - i))
        )
    await db_session.commit()

    report = await svc.movers_report(db_session, USER, from_day=DAY_A, to_day=DAY_B, limit=2)

    assert [r.external_id for r in report.gainers] == ["EQUITY:UP3", "EQUITY:UP2"]
    assert [r.external_id for r in report.losers] == ["EQUITY:DN3", "EQUITY:DN2"]


async def test_no_snapshots_at_all_is_an_empty_report(db_session: AsyncSession) -> None:
    report = await svc.movers_report(db_session, USER)
    assert report.compared_from is None and report.compared_to is None
    assert report.gainers == () and report.note is not None


async def test_capture_stores_the_display_name(db_session: AsyncSession) -> None:
    """The migration is only useful if capture actually fills the column."""

    async def _no_sleep(_s: float) -> None:
        return None

    async def _fx() -> Optional[Decimal]:
        return None

    outcome = await svc.capture_user(
        db_session,
        USER,
        connector=StubConnector(),
        now=datetime(2026, 8, 20, 18, 15, tzinfo=timezone.utc),
        fx=_fx,
        sleep=_no_sleep,
        call_spacing=0,
    )
    assert outcome.status == svc.CAPTURED

    rows = (
        await db_session.execute(
            text("SELECT name FROM snapshot_holdings WHERE name IS NOT NULL")
        )
    ).all()
    assert rows, "capture wrote no display names at all"


# --------------------------------------------------------------------------- #
# The route
# --------------------------------------------------------------------------- #
class _Connector(StubConnector):
    async def link_health(self, user_id: str) -> LinkHealth:
        return LinkHealth.LINKED


@pytest_asyncio.fixture
async def api(test_database_url: str, monkeypatch: pytest.MonkeyPatch):
    """An ASGI client whose sessions live in this test's loop (see S1's fixture)."""
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[Any]:
        async with maker() as session:
            yield session

    monkeypatch.setattr(svc, "get_sessionmaker", lambda: maker)
    connector = _Connector()
    app.dependency_overrides[async_session] = _session
    app.dependency_overrides[svc.optional_session] = _session
    app.dependency_overrides[connector_factory] = lambda: (lambda _uid: connector)
    app.dependency_overrides[connector_for_request] = lambda: connector
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, maker
    finally:
        app.dependency_overrides.clear()
        for task in list(svc._background):
            with suppress(Exception):
                await task
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE users, broker_links, oauth_pending, snapshot_days, "
                    "snapshot_holdings, snapshot_raw, watchlist, portfolio_cache "
                    "RESTART IDENTITY CASCADE"
                )
            )
        await engine.dispose()


async def test_movers_requires_an_identity(api: Any) -> None:
    """No token, no single-tenant flag: 401, never a fall-through to some account."""
    client, _ = api
    assert (await client.get("/portfolio/movers")).status_code == 401


async def test_movers_returns_the_contract_shape(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, maker = api
    async with maker() as session:
        a = await _day(session, DAY_A, user_id="local")
        b = await _day(session, DAY_B, user_id="local")
        session.add_all(
            [
                _holding(a, "EQUITY:MOVER", name="Mover Ltd", units="5", price="200", value="1000"),
                _holding(b, "EQUITY:MOVER", name="Mover Ltd", units="5", price="240", value="1200"),
                _holding(a, "SA:BANK1", asset_type="SA", value="10"),
                _holding(b, "SA:BANK1", asset_type="SA", value="20"),
            ]
        )
        await session.commit()

    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    response = await client.get(
        f"/portfolio/movers?from={DAY_A.isoformat()}&to={DAY_B.isoformat()}&limit=5"
    )
    assert response.status_code == 200
    body = response.json()

    assert body["requested"] == {"from": DAY_A.isoformat(), "to": DAY_B.isoformat()}
    assert body["compared"] == {"from": DAY_A.isoformat(), "to": DAY_B.isoformat()}
    assert body["note"] is None
    assert body["excluded"] == []
    assert [r["external_id"] for r in body["flows"]] == ["SA:BANK1"]

    gainer = body["gainers"][0]
    assert set(gainer) == {
        "source", "external_id", "asset_type", "name", "symbol", "basis",
        "start_price", "end_price", "start_value", "end_value",
        "change_abs", "change_pct", "currency",
    }
    assert gainer["basis"] == "price"
    assert gainer["name"] == "Mover Ltd"
    # Money and percentages stay strings all the way out, like every other
    # figure on this surface.
    for field in ("start_price", "end_price", "start_value", "end_value", "change_abs", "change_pct"):
        assert isinstance(gainer[field], str), field
    assert gainer["change_pct"] == "20.00"


async def test_movers_without_a_database_is_200_with_a_note(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard's live figures do not depend on Postgres; nor does this 200."""
    client, _ = api

    async def _no_session() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[svc.optional_session] = _no_session
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    response = await client.get("/portfolio/movers")

    assert response.status_code == 200
    body = response.json()
    assert body["gainers"] == [] and body["losers"] == [] and body["flows"] == []
    assert body["compared"] == {"from": None, "to": None}
    assert "database" in body["note"].lower()
