"""The `/portfolio/*` read-through cache (issue #15).

The dashboard's three expensive reads now answer from Postgres inside a short
window instead of asking a source that rate-limits 15 calls per minute per tool.
That is only safe while five properties hold, and each one is a test here:

1. **A hit makes no source call**, and a miss (or an expired TTL) makes exactly
   one.
2. **`?fresh=1` is a true bypass** — the Refresh button re-reads the source and
   rewrites the row, so the next reader gets the new reading too.
3. **Failures are never cached.** A 429 or a 502 must not become sticky; the
   next call has to be free to succeed.
4. **No database is no cache**, and no behaviour change: `DATABASE_URL` unset
   means every read goes to the source exactly as it did before.
5. **A cached row is not history.** It is dropped by the prune, by unlink, and
   by the account-deletion cascade (that last one lives in
   `test_account_deletion.py`, with the rest of the schema).

Driven through the real ASGI app against the migrated test database, with the
connector replaced — the point is the route's behaviour, not the source's.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import main
from api.main import app
from api.routes.internal import CRON_SECRET_ENV, CRON_SECRET_HEADER
from api.routes import portfolio as routes
from api.routes.portfolio import connector_for_request
from db.models import PortfolioCache, User
from portfolio.connectors import StubConnector
from portfolio.errors import RateLimited
from portfolio.models import AssetType, BreakdownBy, LinkHealth
from services import portfolio_cache
from services import snapshots as svc

CRON_SECRET = "test-cron-secret"
CRON_AUTH = {CRON_SECRET_HEADER: CRON_SECRET}
USER = "local"


class _Counting(StubConnector):
    """The stub portfolio, plus a tally of what the route actually asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.snapshots = 0
        self.holdings: list[str] = []
        self.allocations: list[str] = []
        self.error: Optional[Exception] = None

    async def link_health(self, user_id: str) -> LinkHealth:
        return LinkHealth.LINKED

    async def fetch_snapshot(self, user_id: str) -> Any:
        self.snapshots += 1
        if self.error is not None:
            raise self.error
        return await super().fetch_snapshot(user_id)

    async def fetch_holdings(self, user_id: str, asset_type: AssetType) -> Any:
        self.holdings.append(asset_type.value)
        if self.error is not None:
            raise self.error
        return await super().fetch_holdings(user_id, asset_type)

    async def fetch_allocation(
        self, user_id: str, asset_type: AssetType, by: BreakdownBy
    ) -> Any:
        self.allocations.append(f"{asset_type.value}:{by.value}")
        if self.error is not None:
            raise self.error
        return await super().fetch_allocation(user_id, asset_type, by)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-tenant dev, so a headerless request reads as ``"local"``."""
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    monkeypatch.setenv(CRON_SECRET_ENV, CRON_SECRET)


@pytest_asyncio.fixture
async def api(test_database_url: str, monkeypatch: pytest.MonkeyPatch):
    """Client, sessionmaker and connector, all bound to this test's event loop.

    Same shape as `test_snapshots_api.py`: the app's engine is a process-wide
    singleton bound to whatever loop built it, so the session dependency is
    overridden rather than pretended to be reusable.
    """
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[Any]:
        async with maker() as session:
            yield session

    monkeypatch.setattr(svc, "get_sessionmaker", lambda: maker)
    # S1's opportunistic capture reads the source too, on a background task whose
    # timing is nobody's business here — it would make "how many source calls did
    # this route make?" a race. Its own behaviour is pinned in `test_snapshots*`.
    monkeypatch.setattr(routes, "schedule_capture_if_missing", lambda *a, **k: None)

    # The cache row is FK'd to `users`, so the caller has to exist. In production
    # `portfolio_identity` writes that row from the verified token.
    async with maker() as session:
        session.add(User(id=USER))
        await session.commit()

    connector = _Counting()
    app.dependency_overrides[svc.optional_session] = _session
    app.dependency_overrides[connector_for_request] = lambda: connector
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, maker, connector
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(
                text("TRUNCATE users, portfolio_cache RESTART IDENTITY CASCADE")
            )
        await engine.dispose()


async def _cache_rows(maker: Any) -> list[str]:
    async with maker() as session:
        keys = await session.execute(
            select(PortfolioCache.cache_key).order_by(PortfolioCache.cache_key)
        )
        return list(keys.scalars().all())


async def _age(maker: Any, key: str, seconds: int) -> None:
    """Backdate a row's `fetched_at`, the way waiting out a TTL would."""
    async with maker() as session:
        await session.execute(
            update(PortfolioCache)
            .where(PortfolioCache.cache_key == key)
            .values(fetched_at=datetime.now(timezone.utc) - timedelta(seconds=seconds))
        )
        await session.commit()


# --------------------------------------------------------------------------- #
# Hit, miss, expiry
# --------------------------------------------------------------------------- #
async def test_summary_is_read_through_and_the_second_read_is_free(api: Any) -> None:
    client, maker, connector = api

    first = await client.get("/portfolio/summary")
    assert first.status_code == 200
    assert connector.snapshots == 1

    second = await client.get("/portfolio/summary")
    assert second.status_code == 200
    assert connector.snapshots == 1, "a hit must not touch the source"
    assert second.json()["net_worth"] == first.json()["net_worth"]
    assert await _cache_rows(maker) == ["summary"]


async def test_summary_re_reads_once_the_ttl_has_passed(api: Any) -> None:
    client, maker, connector = api
    await client.get("/portfolio/summary")
    await _age(maker, "summary", 301)

    await client.get("/portfolio/summary")
    assert connector.snapshots == 2
    # And the row was rewritten rather than duplicated.
    assert await _cache_rows(maker) == ["summary"]


async def test_a_cache_hit_still_carries_a_fresh_last_captured_at(api: Any) -> None:
    """The staleness stamp is local data, and is never served from the payload.

    A capture that lands after the payload was cached has to show up on the very
    next page load, or the dashboard tells someone their history stopped when it
    did not.
    """
    client, maker, connector = api
    assert (await client.get("/portfolio/summary")).json()["last_captured_at"] is None

    async def _no_sleep(_s: float) -> None:
        return None

    async def _fx() -> Any:
        return None

    async with maker() as session:
        await svc.capture_user(
            session,
            USER,
            connector=connector,
            now=datetime.now(timezone.utc),
            fx=_fx,
            sleep=_no_sleep,
            call_spacing=0,
        )

    hit = await client.get("/portfolio/summary")
    assert hit.json()["last_captured_at"] is not None


async def test_holdings_are_cached_per_asset_type(api: Any) -> None:
    client, maker, connector = api

    await client.get("/portfolio/holdings?asset_type=MF")
    await client.get("/portfolio/holdings?asset_type=MF")
    assert connector.holdings == ["MF"]

    # A different bucket is a different question, so it is a different key.
    await client.get("/portfolio/holdings?asset_type=IND_STOCK")
    assert connector.holdings == ["MF", "IND_STOCK"]
    assert await _cache_rows(maker) == ["holdings:IND_STOCK", "holdings:MF"]


async def test_allocation_is_cached_for_the_attributed_ist_day(api: Any) -> None:
    """The drill-down that made this issue: instant after its first fetch today.

    The key carries the attributed IST day from `services.snapshots`, so the row
    expires by name at the day boundary the rest of the app already agrees on —
    never a UTC "today".
    """
    client, maker, connector = api

    await client.get("/portfolio/allocation?asset_type=MF&by=sector")
    await client.get("/portfolio/allocation?asset_type=MF&by=sector")
    assert connector.allocations == ["MF:sector"]

    today = svc.attributed_day(datetime.now(timezone.utc))
    assert await _cache_rows(maker) == [f"allocation:MF:sector:{today.isoformat()}"]

    # Yesterday's row is a different key, so it can never answer today's question.
    assert portfolio_cache.allocation_key(
        "MF", "sector", today - timedelta(days=1)
    ) != portfolio_cache.allocation_key("MF", "sector", today)


# --------------------------------------------------------------------------- #
# fresh=1 — the Refresh button
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path",
    (
        "/portfolio/summary",
        "/portfolio/holdings?asset_type=MF",
        "/portfolio/allocation?asset_type=MF&by=sector",
    ),
)
async def test_fresh_bypasses_the_cache_on_every_cached_route(
    api: Any, path: str
) -> None:
    client, maker, connector = api
    joiner = "&" if "?" in path else "?"

    await client.get(path)
    await client.get(f"{path}{joiner}fresh=1")

    calls = connector.snapshots + len(connector.holdings) + len(connector.allocations)
    assert calls == 2, "fresh=1 must re-read the source"
    # …and it rewrites the row, so the *next* reader gets the new reading too.
    assert len(await _cache_rows(maker)) == 1
    before = await _cache_rows(maker)
    await client.get(path)
    assert await _cache_rows(maker) == before
    assert connector.snapshots + len(connector.holdings) + len(connector.allocations) == 2


# --------------------------------------------------------------------------- #
# What must never be cached
# --------------------------------------------------------------------------- #
async def test_an_error_response_is_never_cached(api: Any) -> None:
    """A 429 that stuck would turn a passing condition into a permanent one."""
    client, maker, connector = api
    connector.error = RateLimited("fetch_snapshot", "RATE_LIMIT", retry_after=3)

    failed = await client.get("/portfolio/summary")
    assert failed.status_code == 429
    assert await _cache_rows(maker) == []

    # And the failure poisoned nothing: the next call is free to succeed.
    connector.error = None
    assert (await client.get("/portfolio/summary")).status_code == 200
    assert await _cache_rows(maker) == ["summary"]


async def test_with_no_database_every_read_goes_to_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DB-optional invariant: no `DATABASE_URL`, no cache, no change."""
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    connector = _Counting()
    app.dependency_overrides[connector_for_request] = lambda: connector
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.get("/portfolio/summary")).status_code == 200
            assert (await client.get("/portfolio/summary")).status_code == 200
    finally:
        app.dependency_overrides.clear()
    assert connector.snapshots == 2


# --------------------------------------------------------------------------- #
# Retention and invalidation
# --------------------------------------------------------------------------- #
async def test_prune_drops_stale_cache_rows_and_keeps_current_ones(api: Any) -> None:
    client, maker, _ = api
    await client.get("/portfolio/summary")
    await client.get("/portfolio/holdings?asset_type=MF")
    await _age(maker, "summary", int(timedelta(days=3).total_seconds()))

    response = await client.post("/internal/prune", headers=CRON_AUTH)
    assert response.status_code == 200
    assert response.json()["cache_deleted"] == 1
    assert await _cache_rows(maker) == ["holdings:MF"]


async def test_unlink_invalidates_the_users_cache(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rows describe an account the user just disconnected.

    The revoke-and-delete half of unlink is `test_auth_unlink.py`'s subject and is
    stubbed out here (it talks to a broker); what this pins is that the route
    drops the cached holdings along with the credential.
    """
    client, maker, _ = api

    async def _logout(user_id: str) -> dict[str, Any]:
        return {"revoked_upstream": None}

    monkeypatch.setattr(main, "logout", _logout)

    await client.get("/portfolio/summary")
    await client.get("/portfolio/holdings?asset_type=MF")
    assert len(await _cache_rows(maker)) == 2

    response = await client.post("/auth/unlink")
    assert response.status_code == 200
    assert await _cache_rows(maker) == []


# --------------------------------------------------------------------------- #
# The helper's own degradation rules
# --------------------------------------------------------------------------- #
async def test_the_helper_is_a_no_op_without_a_session() -> None:
    """`session is None` is a permanent miss and a silent no-op write."""
    assert await portfolio_cache.get(None, USER, "summary", max_age=300) is None
    await portfolio_cache.put(None, USER, "summary", {"net_worth": "1"})
    assert await portfolio_cache.invalidate_user(None, USER) == 0


async def test_a_write_failure_never_reaches_the_reader(api: Any) -> None:
    """A cache that cannot be written costs a slow page, never a dead one."""
    client, maker, connector = api
    # No `users` row is a foreign-key violation on write — the bluntest failure
    # the cache can hit, and the reader must not be able to tell.
    async with maker() as session:
        await session.execute(delete(User).where(User.id == USER))
        await session.commit()

    assert (await client.get("/portfolio/summary")).status_code == 200
    assert connector.snapshots == 1
    async with maker() as session:
        rows = await session.execute(select(func.count()).select_from(PortfolioCache))
        assert rows.scalar_one() == 0
