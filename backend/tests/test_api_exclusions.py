"""`/portfolio/exclusions` and every figure it reaches, against the real Postgres.

The claims pinned here:

1. **CRUD round-trips, idempotently.** Excluding twice is one row (201 then
   200); restoring removes it; another user's id is a **404**, never a 403.
2. **Durable or an error.** No database: reads degrade with a note, writes 503.
3. **Manual rows are deleted, not excluded** — a 422 at the schema.
4. **History re-prices at read time.** Each captured day loses the value
   captured for the excluded holding *that day*, and restoring puts it back —
   the snapshot rows themselves are never touched.
5. **Movers ignore an excluded holding.**
6. **Changing the set discards today's saved AI overview**, so the next one is
   written from the adjusted figures.
7. **It cascades** with the user.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from api import main
from api.routes import portfolio as portfolio_routes
from api.routes.overview import _overview_key
from api.routes.portfolio import connector_for_request
from db.models import HoldingExclusion, SnapshotDay, SnapshotHolding, User, utcnow
from portfolio.connectors import StubConnector
from services import adoption, portfolio_cache
from services import snapshots as snapshot_svc
from services.snapshots import attributed_day
from tests.clerk_stub import bearer, clerk, clerk_key  # noqa: F401
from tools import ind_money_auth as auth

USER_A = "user_2eeeeeeeeeeeeeeeeeeeeeeeea"
USER_B = "user_2eeeeeeeeeeeeeeeeeeeeeeeeb"

FD_ROW = {
    "source": "ind_money",
    "external_id": "FD:KOTAK1",
    "asset_type": "FD",
    "name": "Kotak Mahindra Bank Limited",
}

DAY_1 = date(2026, 11, 1)
DAY_2 = date(2026, 11, 2)
#: Pins `history_points`' window so the fixed days above are always inside it.
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    monkeypatch.delenv(adoption.OPERATOR_EMAIL_ENV, raising=False)
    auth.reset_auth_stores()
    adoption.reset_adoption_cache()
    portfolio_routes.reset_connector()
    yield
    auth.reset_auth_stores()
    adoption.reset_adoption_cache()
    portfolio_routes.reset_connector()
    main.app.dependency_overrides.clear()


@pytest.fixture
async def client(db_env: Any) -> Any:
    main.app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://testserver"
    ) as http:
        yield http


@pytest.fixture
async def no_db_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://testserver"
    ) as http:
        yield http


async def _exclude(client: Any, key: rsa.RSAPrivateKey, user: str, **overrides: Any) -> Any:
    return await client.post(
        "/portfolio/exclusions", json={**FD_ROW, **overrides}, headers=bearer(key, user)
    )


async def _seed_history(maker: Any, user: str) -> None:
    """Two captured days, each carrying the excluded FD and one fund."""
    async with maker() as session:
        await session.execute(
            text("INSERT INTO users (id, created_at) VALUES (:i, :t) ON CONFLICT DO NOTHING"),
            {"i": user, "t": utcnow()},
        )
        for captured_on, total, fd_value in ((DAY_1, "100171", "171"), (DAY_2, "101162", "162")):
            day = SnapshotDay(
                user_id=user,
                captured_on=captured_on,
                total_value=Decimal(total),
                captured_at=datetime(
                    captured_on.year, captured_on.month, captured_on.day, 18, tzinfo=timezone.utc
                ),
            )
            session.add(day)
            await session.flush()
            session.add(
                SnapshotHolding(
                    snapshot_id=day.id,
                    source="ind_money",
                    external_id=FD_ROW["external_id"],
                    asset_type="FD",
                    current_value=Decimal(fd_value),
                )
            )
            session.add(
                SnapshotHolding(
                    snapshot_id=day.id,
                    source="ind_money",
                    external_id="EQUITY:INFY",
                    asset_type="EQUITY",
                    units=Decimal("10"),
                    current_price=Decimal("10000") if captured_on == DAY_1 else Decimal("10100"),
                    current_value=Decimal("100000") if captured_on == DAY_1 else Decimal("101000"),
                )
            )
        await session.commit()


# --------------------------------------------------------------------------- #
# 1. CRUD
# --------------------------------------------------------------------------- #
async def test_exclude_list_restore_round_trip(client: Any, clerk: rsa.RSAPrivateKey) -> None:
    created = await _exclude(client, clerk, USER_A)
    assert created.status_code == 201, created.text
    row = created.json()
    assert {k: row[k] for k in FD_ROW} == FD_ROW
    assert row["id"] and row["created_at"]

    listed = await client.get("/portfolio/exclusions", headers=bearer(clerk, USER_A))
    assert listed.json() == {"exclusions": [row], "note": None}

    gone = await client.delete(
        f"/portfolio/exclusions/{row['id']}", headers=bearer(clerk, USER_A)
    )
    assert gone.status_code == 204
    listed = await client.get("/portfolio/exclusions", headers=bearer(clerk, USER_A))
    assert listed.json()["exclusions"] == []


async def test_excluding_twice_is_one_row(
    client: Any, db_env: Any, clerk: rsa.RSAPrivateKey
) -> None:
    first = await _exclude(client, clerk, USER_A)
    second = await _exclude(client, clerk, USER_A)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    async with db_env() as session:
        count = await session.scalar(select(func.count()).select_from(HoldingExclusion))
    assert count == 1


async def test_another_users_exclusion_is_invisible_and_404(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    row = (await _exclude(client, clerk, USER_A)).json()
    listed = await client.get("/portfolio/exclusions", headers=bearer(clerk, USER_B))
    assert listed.json()["exclusions"] == []
    stolen = await client.delete(
        f"/portfolio/exclusions/{row['id']}", headers=bearer(clerk, USER_B)
    )
    assert stolen.status_code == 404
    still = await client.get("/portfolio/exclusions", headers=bearer(clerk, USER_A))
    assert [r["id"] for r in still.json()["exclusions"]] == [row["id"]]


async def test_every_method_requires_an_identity(client: Any) -> None:
    assert (await client.get("/portfolio/exclusions")).status_code == 401
    assert (await client.post("/portfolio/exclusions", json=FD_ROW)).status_code == 401
    assert (await client.delete("/portfolio/exclusions/abc")).status_code == 401


# --------------------------------------------------------------------------- #
# 2-3. No database, and validation
# --------------------------------------------------------------------------- #
async def test_without_a_database_reads_degrade_and_writes_503(
    no_db_client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    listed = await no_db_client.get("/portfolio/exclusions", headers=bearer(clerk, USER_A))
    assert listed.status_code == 200
    assert listed.json()["exclusions"] == []
    assert listed.json()["note"]
    written = await _exclude(no_db_client, clerk, USER_A)
    assert written.status_code == 503
    assert written.json()["detail"]["code"] == "no_database"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"source": "manual"}, id="manual-row"),
        pytest.param({"external_id": ""}, id="blank-id"),
        pytest.param({"colour": "red"}, id="unknown-field"),
    ],
)
async def test_create_rejects_what_cannot_be_excluded(
    client: Any, clerk: rsa.RSAPrivateKey, overrides: dict
) -> None:
    response = await _exclude(client, clerk, USER_A, **overrides)
    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# 4-5. History and movers
# --------------------------------------------------------------------------- #
async def test_history_drops_the_excluded_holding_per_day_and_restores_it(
    client: Any, db_env: Any, clerk: rsa.RSAPrivateKey
) -> None:
    await _seed_history(db_env, USER_A)

    async def totals() -> list[Decimal]:
        async with db_env() as session:
            points = await snapshot_svc.history_points(session, USER_A, days=30, now=NOW)
        return [p.total_value for p in points]

    assert await totals() == [Decimal("100171"), Decimal("101162")]

    row = (await _exclude(client, clerk, USER_A)).json()
    assert await totals() == [Decimal("100000"), Decimal("101000")]

    await client.delete(f"/portfolio/exclusions/{row['id']}", headers=bearer(clerk, USER_A))
    assert await totals() == [Decimal("100171"), Decimal("101162")]

    # The captured rows themselves were never rewritten.
    async with db_env() as session:
        stored = await session.scalars(
            select(SnapshotDay.total_value).order_by(SnapshotDay.captured_on)
        )
        assert list(stored) == [Decimal("100171.00"), Decimal("101162.00")]


async def test_movers_never_list_an_excluded_holding(
    client: Any, db_env: Any, clerk: rsa.RSAPrivateKey
) -> None:
    await _seed_history(db_env, USER_A)

    async def ids() -> set[str]:
        async with db_env() as session:
            report = await snapshot_svc.movers_report(
                session, USER_A, from_day=DAY_1, to_day=DAY_2, now=NOW
            )
        rows = (*report.gainers, *report.losers, *report.flows, *report.opened, *report.closed)
        return {r.external_id for r in rows}

    assert await ids() == {"FD:KOTAK1", "EQUITY:INFY"}
    await _exclude(client, clerk, USER_A)
    assert await ids() == {"EQUITY:INFY"}


# --------------------------------------------------------------------------- #
# 6. The saved overview
# --------------------------------------------------------------------------- #
async def test_changing_the_set_discards_todays_saved_overview(
    client: Any, db_env: Any, clerk: rsa.RSAPrivateKey
) -> None:
    key = _overview_key(attributed_day(datetime.now(timezone.utc)))

    async def saved() -> Any:
        async with db_env() as session:
            return await portfolio_cache.get(session, USER_A, key)

    async def save() -> None:
        async with db_env() as session:
            await session.execute(
                text("INSERT INTO users (id, created_at) VALUES (:i, :t) ON CONFLICT DO NOTHING"),
                {"i": USER_A, "t": utcnow()},
            )
            await session.commit()
            await portfolio_cache.put(session, USER_A, key, {"narrative": []})

    await save()
    row = (await _exclude(client, clerk, USER_A)).json()
    assert await saved() is None

    await save()
    await client.delete(f"/portfolio/exclusions/{row['id']}", headers=bearer(clerk, USER_A))
    assert await saved() is None


# --------------------------------------------------------------------------- #
# 7. Cascade
# --------------------------------------------------------------------------- #
async def test_deleting_the_user_leaves_zero_exclusions(
    client: Any, db_env: Any, clerk: rsa.RSAPrivateKey
) -> None:
    await _exclude(client, clerk, USER_A)
    async with db_env() as session:
        await session.execute(User.__table__.delete().where(User.id == USER_A))
        await session.commit()
        count = await session.scalar(select(func.count()).select_from(HoldingExclusion))
    assert count == 0
