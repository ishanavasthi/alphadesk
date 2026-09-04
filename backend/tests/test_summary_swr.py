"""Stale-while-revalidate for `/portfolio/summary` (issue #72, phase 3).

A summary row older than the 5-minute TTL but younger than
`SUMMARY_STALE_MAX_SECONDS` is served instantly — the "fetched N ago" stamp
says exactly how old — while a single-flight background task rewrites it for
the next reader. Pinned:

1. A stale row is served immediately (the seeded marker comes back), and after
   the background task drains the next read is the live value.
2. Exactly one revalidation runs no matter how many stale opens race it.
3. Past the cap the reader waits for a real read; `fresh=1` bypasses stale too.

Runs against the stub connector with the opportunistic capture stubbed out
(it would spend source calls behind the test's back on an empty database).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import api.routes.portfolio as routes
from api.main import app
from api.routes.portfolio import connector_for_request
from db.models import User
from portfolio.connectors import PortfolioConnector
from services import portfolio_cache
from tests.test_holdings_all import _Counting


@pytest.fixture(autouse=True)
def local_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")


@pytest.fixture
def quiet_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "schedule_capture_if_missing", lambda *a, **k: None)


async def _seed_stale(maker, age: timedelta) -> None:
    """A summary row reading `1.00`, backdated by `age`."""
    async with maker() as session:
        session.add(User(id="local"))
        await session.commit()
    async with maker() as session:
        await portfolio_cache.put(
            session, "local", portfolio_cache.summary_key(),
            {"net_worth": "1.00", "by_asset_type": []},
        )
    async with maker() as session:
        await session.execute(
            text(
                "UPDATE portfolio_cache SET fetched_at = now() - "
                "make_interval(secs => :secs) "
                "WHERE user_id = 'local' AND cache_key = 'summary'"
            ),
            {"secs": age.total_seconds()},
        )
        await session.commit()


def _client(connector: PortfolioConnector) -> Iterator[TestClient]:
    app.dependency_overrides[connector_for_request] = lambda: connector
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(connector_for_request, None)


async def test_stale_served_now_revalidated_once(
    db_env, quiet_capture
) -> None:
    await _seed_stale(db_env, timedelta(hours=1))
    connector = _Counting()
    for client in _client(connector):
        first = client.get("/portfolio/summary").json()
        assert first["net_worth"] == "1.00"  # stale, served instantly
        second = client.get("/portfolio/summary").json()
        assert second["net_worth"] == "1.00"  # still stale: one flight only
        await asyncio.sleep(2)  # let the background rewrite land
        third = client.get("/portfolio/summary").json()
        assert third["net_worth"] != "1.00"  # live value from the stub
    assert connector.snapshot_calls == 1  # single-flight: two opens, one rewrite


async def test_past_the_cap_waits_for_a_real_read(
    db_env, quiet_capture
) -> None:
    await _seed_stale(db_env, timedelta(hours=7))
    connector = _Counting()
    for client in _client(connector):
        body = client.get("/portfolio/summary").json()
        assert body["net_worth"] != "1.00"
    assert connector.snapshot_calls == 1


async def test_fresh_bypasses_stale(db_env, quiet_capture) -> None:
    await _seed_stale(db_env, timedelta(hours=1))
    connector = _Counting()
    for client in _client(connector):
        body = client.get("/portfolio/summary?fresh=1").json()
        assert body["net_worth"] != "1.00"
