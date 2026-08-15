"""The HTTP surface of card S1: the cron gate, and the routes it lights up.

Two groups, deliberately separate:

- **the gate**, which needs no database at all, because the whole point is that
  it refuses before anything expensive happens;
- **the routes**, driven through an ASGI client against the real migrated test
  database, so `/portfolio/history` is asserted on rows that actually went
  through the capture service rather than on a hand-built fixture.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, AsyncIterator, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.main import app
from api.routes.internal import CRON_SECRET_ENV, CRON_SECRET_HEADER
from api.routes.portfolio import get_connector
from db.session import async_session
from portfolio.connectors import StubConnector
from portfolio.errors import NotLinked
from portfolio.models import LinkHealth, PortfolioSnapshot
from services import snapshots as svc

CRON_SECRET = "test-cron-secret"
CRON_AUTH = {CRON_SECRET_HEADER: CRON_SECRET}
ADMIN_SECRET = "test-admin-secret"
ADMIN_AUTH = {"x-alphadesk-admin-secret": ADMIN_SECRET}

INTERNAL_ROUTES = ("/internal/snapshot", "/internal/prune")

PRIMARY_RUN = datetime(2026, 8, 16, 18, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def secrets_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CRON_SECRET_ENV, CRON_SECRET)
    monkeypatch.setenv("ALPHADESK_ADMIN_SECRET", ADMIN_SECRET)
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)


# --------------------------------------------------------------------------- #
# The cron gate — no database involved, on purpose
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def gate_client() -> AsyncIterator[AsyncClient]:
    """A client with no DB wiring: every request here must fail at the gate."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.parametrize("path", INTERNAL_ROUTES)
async def test_missing_cron_secret_is_401(gate_client: AsyncClient, path: str) -> None:
    response = await gate_client.post(path)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "bad_cron_secret"


@pytest.mark.parametrize("path", INTERNAL_ROUTES)
async def test_wrong_cron_secret_is_401(gate_client: AsyncClient, path: str) -> None:
    response = await gate_client.post(path, headers={CRON_SECRET_HEADER: "nope"})
    assert response.status_code == 401


@pytest.mark.parametrize("path", INTERNAL_ROUTES)
async def test_unset_cron_secret_fails_closed(
    gate_client: AsyncClient, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset env locks the route rather than opening it — and says so distinctly.

    503 rather than 401 on purpose: an operator staring at a red workflow has to
    be able to tell "you never configured me" from "your secret is wrong", and
    those are the two mistakes that actually get made.
    """
    monkeypatch.delenv(CRON_SECRET_ENV, raising=False)
    response = await gate_client.post(path, headers=CRON_AUTH)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "cron_not_configured"


async def test_the_admin_secret_does_not_open_the_cron_routes(
    gate_client: AsyncClient,
) -> None:
    """Separate caller, separate secret. A CI runner must not be handed a key
    that can also read holdings and unlink the account."""
    response = await gate_client.post("/internal/snapshot", headers=ADMIN_AUTH)
    assert response.status_code == 401


async def test_the_cron_secret_does_not_open_the_portfolio_routes(
    gate_client: AsyncClient,
) -> None:
    """...and the converse, so the two gates cannot quietly become one."""
    response = await gate_client.get("/portfolio/summary", headers=CRON_AUTH)
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# The routes, against the real migrated database
# --------------------------------------------------------------------------- #
async def _fixed_rate() -> Optional[Decimal]:
    return Decimal("87.5")


class _Connector(StubConnector):
    def __init__(self, *, snapshot_error: Optional[Exception] = None) -> None:
        super().__init__()
        self._snapshot_error = snapshot_error

    async def fetch_snapshot(self, user_id: str) -> PortfolioSnapshot:
        if self._snapshot_error is not None:
            raise self._snapshot_error
        return await super().fetch_snapshot(user_id)

    async def link_health(self, user_id: str) -> LinkHealth:
        return LinkHealth.LINKED


@pytest_asyncio.fixture
async def api(test_database_url: str, monkeypatch: pytest.MonkeyPatch):
    """An ASGI client whose DB sessions live in *this* test's event loop.

    The app's own engine is a process-wide singleton bound to whatever loop
    created it, which asyncpg does not survive being moved off. Overriding the
    two session dependencies is the honest way to point the routes at the
    throwaway test database without pretending the singleton is reusable.
    """
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[Any]:
        async with maker() as session:
            yield session

    # The background/awaited capture paths open their *own* session, because in
    # production their caller is a task with no request to borrow one from. Point
    # that factory at the test database too.
    monkeypatch.setattr(svc, "get_sessionmaker", lambda: maker)
    # No live FX call and no real pacing from a test: the rate is covered by its
    # own unit tests, and 1.5s per bucket would make this file take a minute to
    # assert things that have nothing to do with pacing.
    monkeypatch.setattr(svc, "fetch_usd_inr", _fixed_rate)
    monkeypatch.setattr(svc, "CALL_SPACING_SECONDS", 0.0)

    connector = _Connector()
    app.dependency_overrides[async_session] = _session
    app.dependency_overrides[svc.optional_session] = _session
    app.dependency_overrides[get_connector] = lambda: connector
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, maker, connector
    finally:
        app.dependency_overrides.clear()
        # Let any fire-and-forget capture finish before the tables go away, so a
        # stray task cannot fail a later test from the previous one's teardown.
        for task in list(svc._background):
            with suppress(Exception):
                await task
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE users, broker_links, oauth_pending, snapshot_days, "
                    "snapshot_holdings, snapshot_raw RESTART IDENTITY CASCADE"
                )
            )
        await engine.dispose()


async def _capture_via_service(maker: Any, connector: Any, when: datetime) -> None:
    async def _no_sleep(_s: float) -> None:
        return None

    async def _fx() -> Optional[Decimal]:
        return Decimal("87.5")

    async with maker() as session:
        await svc.capture_user(
            session,
            "local",
            connector=connector,
            now=when,
            fx=_fx,
            sleep=_no_sleep,
            call_spacing=0,
        )


async def test_internal_snapshot_captures_and_is_idempotent(api: Any) -> None:
    client, maker, _ = api

    first = await client.post("/internal/snapshot", headers=CRON_AUTH)
    assert first.status_code == 200
    body = first.json()
    assert body["users_captured"] == 1
    assert body["errors"] == 0
    assert body["captured_on"]

    second = await client.post("/internal/snapshot", headers=CRON_AUTH)
    assert second.status_code == 200
    assert second.json()["users_captured"] == 0
    assert second.json()["skipped"] == 1

    async with maker() as session:
        points = await svc.history_points(session, "local", days=90)
    assert len(points) == 1


async def test_internal_snapshot_reports_errors_without_failing_the_request(
    api: Any,
) -> None:
    """A user-level failure is data in the body, not a 5xx.

    The workflow retries on 5xx. If "one account is unlinked" arrived as a 502,
    the retry would hammer a perfectly healthy backend all night.
    """
    client, _, _ = api
    app.dependency_overrides[get_connector] = lambda: _Connector(
        snapshot_error=NotLinked("no credential")
    )
    response = await client.post("/internal/snapshot", headers=CRON_AUTH)
    assert response.status_code == 200
    assert response.json() == {
        **response.json(),
        "users_captured": 0,
        "skipped": 1,
        "errors": 0,
    }


async def test_history_returns_the_captured_points(api: Any) -> None:
    client, maker, connector = api
    for offset in (2, 1, 0):
        await _capture_via_service(maker, connector, PRIMARY_RUN - timedelta(days=offset))

    body = (await client.get("/portfolio/history?days=90", headers=ADMIN_AUTH)).json()
    assert len(body["points"]) == 3
    dates = [p["date"] for p in body["points"]]
    assert dates == sorted(dates)
    # Money stays a string all the way out, as everywhere else on this surface.
    assert all(isinstance(p["net_worth"], str) for p in body["points"])
    assert body["last_captured_at"] is not None
    assert body["note"] is None


async def test_summary_carries_last_captured_at(api: Any) -> None:
    client, maker, connector = api
    before = (await client.get("/portfolio/summary", headers=ADMIN_AUTH)).json()
    assert before["last_captured_at"] is None

    await _capture_via_service(maker, connector, PRIMARY_RUN)
    after = (await client.get("/portfolio/summary", headers=ADMIN_AUTH)).json()
    assert after["last_captured_at"] is not None


async def test_capture_button_route_is_admin_gated_and_idempotent(api: Any) -> None:
    client, maker, _ = api

    assert (await client.post("/portfolio/capture")).status_code == 401

    first = await client.post("/portfolio/capture", headers=ADMIN_AUTH)
    assert first.status_code == 200
    assert first.json()["status"] == svc.CAPTURED

    second = await client.post("/portfolio/capture", headers=ADMIN_AUTH)
    assert second.json()["status"] == svc.ALREADY_CAPTURED

    async with maker() as session:
        assert len(await svc.history_points(session, "local", days=90)) == 1


async def test_prune_route_reports_what_it_deleted(api: Any) -> None:
    client, maker, connector = api
    await _capture_via_service(maker, connector, PRIMARY_RUN)

    async with maker() as session:
        await session.execute(
            text("UPDATE snapshot_raw SET captured_at = now() - interval '200 days'")
        )
        await session.commit()

    response = await client.post("/internal/prune?days=90", headers=CRON_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] > 0 and body["days"] == 90

    # The history itself is untouched — only the forensic copies went.
    async with maker() as session:
        assert len(await svc.history_points(session, "local", days=90)) == 1
