"""`GET /portfolio/holdings/all` — the batch bucket walk (issue #72, phase 2).

The dashboard used to walk N sequential `GET /holdings?asset_type=` calls; this
endpoint fans the same reads out concurrently server-side (same per-bucket
cache rows, same status vocabulary) and returns them in one response. Pinned:

1. **Shape.** One entry per bucket the snapshot reported, each with
   `asset_type` / `status` / `holdings` / `retry_after`, statuses from the
   closed set — never a raised error for a servable snapshot.
2. **Error mapping.** A bucket the source cannot serve is labelled
   (`unsupported`, `unverified`, `rate_limited`, `error`); a throttled bucket
   is waited out once, then labelled rather than retried forever.
3. **Cache reuse.** A warmed second walk makes zero source calls; `fresh=1`
   bypasses and re-reads.

The counting connector delegates its snapshot to the stub's invented
portfolio, so no network is touched; the DB cases run against the throwaway
test database.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.portfolio import connector_for_request
from portfolio.connectors import PortfolioConnector, StubConnector
from portfolio.errors import (
    PortfolioSourceError,
    RateLimited,
    SourceUnavailable,
    UnsupportedAssetType,
    UnverifiedShapeError,
)
from portfolio.models import AssetType, BreakdownBy, LinkHealth

STATUSES = {"ok", "unsupported", "unverified", "rate_limited", "error"}


class _Counting(PortfolioConnector):
    """Stub snapshot, scripted holdings failures, call counts for cache proofs."""

    source = "counting"

    def __init__(self, holdings_error: PortfolioSourceError | None = None) -> None:
        self._error = holdings_error
        self.snapshot_calls = 0
        self.holdings_calls = 0
        self._stub = StubConnector()

    async def fetch_snapshot(self, user_id: str) -> Any:
        self.snapshot_calls += 1
        return await self._stub.fetch_snapshot(user_id)

    async def fetch_holdings(self, user_id: str, asset_type: AssetType) -> Any:
        self.holdings_calls += 1
        if self._error is not None:
            raise self._error
        return await self._stub.fetch_holdings(user_id, asset_type)

    async def fetch_allocation(
        self, user_id: str, asset_type: AssetType, by: BreakdownBy
    ) -> Any:
        return await self._stub.fetch_allocation(user_id, asset_type, by)

    async def fetch_sips(self, user_id: str) -> Any:
        return await self._stub.fetch_sips(user_id)

    async def link_health(self, user_id: str) -> LinkHealth:
        return LinkHealth.LINKED


@pytest.fixture(autouse=True)
def local_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")


@pytest.fixture(autouse=True)
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _client(connector: PortfolioConnector) -> Iterator[TestClient]:
    app.dependency_overrides[connector_for_request] = lambda: connector
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(connector_for_request, None)


@pytest.fixture
def stub_client() -> Iterator[TestClient]:
    yield from _client(StubConnector())


def test_batch_covers_every_reported_bucket(stub_client: TestClient) -> None:
    body = stub_client.get("/portfolio/holdings/all").json()
    kinds = [b["asset_type"] for b in body["buckets"]]
    assert kinds == ["MF", "IND_STOCK", "US_STOCK", "UNKNOWN", "FD", "SA", "EPF"]
    for bucket in body["buckets"]:
        assert set(bucket) == {"asset_type", "status", "holdings", "retry_after"}
        assert bucket["status"] in STATUSES
    by_kind = {b["asset_type"]: b for b in body["buckets"]}
    assert by_kind["MF"]["status"] == "ok" and by_kind["MF"]["holdings"]
    # The stub serves EPF rows; the unservable-status mapping is pinned below
    # with scripted failures instead of depending on stub coverage.
    assert "EPF" in by_kind


def _batched(error: PortfolioSourceError) -> dict[str, Any]:
    connector = _Counting(holdings_error=error)
    for client in _client(connector):
        return client.get("/portfolio/holdings/all").json()
    raise AssertionError("unreachable")


def test_throttled_buckets_wait_once_then_label() -> None:
    body = _batched(RateLimited("networth_holdings", "rate_limit_exceeded", retry_after=30))
    assert {b["status"] for b in body["buckets"]} == {"rate_limited"}
    assert all(b["retry_after"] == 30 for b in body["buckets"])


def test_unservable_buckets_are_labelled_not_raised() -> None:
    body = _batched(UnsupportedAssetType("networth_holdings", "unsupported"))
    assert {b["status"] for b in body["buckets"]} == {"unsupported"}
    body = _batched(UnverifiedShapeError("networth_holdings", "unverified"))
    assert {b["status"] for b in body["buckets"]} == {"unverified"}
    body = _batched(SourceUnavailable("networth_holdings", "down"))
    assert {b["status"] for b in body["buckets"]} == {"error"}


async def test_second_walk_is_free_and_fresh_re_reads(db_env, monkeypatch) -> None:
    """Warmed caches answer the second walk with zero source calls."""
    from db.models import User

    import api.routes.portfolio as routes

    # Silence S1's opportunistic background capture: on an empty test database
    # `/summary` would otherwise fire a capture that spends source calls behind
    # the test's back (same reason `test_portfolio_cache.py` stubs it).
    monkeypatch.setattr(routes, "schedule_capture_if_missing", lambda *a, **k: None)

    # The cache row is FK'd to `users`; without the row every write misses.
    async with db_env() as session:
        session.add(User(id="local"))
        await session.commit()

    connector = _Counting()
    for client in _client(connector):
        assert client.get("/portfolio/summary").status_code == 200
        body = client.get("/portfolio/holdings/all").json()
        assert len(body["buckets"]) == 7
        # The summary call warmed the summary cache, so the walk enumerated
        # from it: exactly one holdings read per bucket, no snapshot re-read.
        assert connector.snapshot_calls == 1
        walked = connector.holdings_calls
        assert walked == 7
        client.get("/portfolio/holdings/all")
        assert connector.holdings_calls == walked  # second walk is free
        assert connector.snapshot_calls == 1
        client.get("/portfolio/holdings/all?fresh=1")
        assert connector.holdings_calls > walked  # bypass re-reads the source
