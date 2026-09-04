"""`Server-Timing` instrumentation (issue #72, phase 0).

The latency work must argue from numbers, so the portfolio routes report
theirs: a `total` span on every response from the middleware, plus `db` / `src`
/ `cache` spans around the two phases of the expensive reads. Pinned here:

1. Every portfolio read carries a `Server-Timing` header with a `total` span.
2. A cache-hit summary reports a `cache` span and no `src` span (nothing was
   asked of the source); a holdings miss reports `src` (the walk happened).
3. Span names are a closed set — never a user id, asset type, or query string.

Runs against the stub connector in single-tenant mode with no database, so no
network and no services are touched.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.portfolio import connector_for_request
from portfolio.connectors import PortfolioConnector, StubConnector


@pytest.fixture(autouse=True)
def local_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")


@pytest.fixture(autouse=True)
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(connector_for_request, None)


def _spans(response) -> dict[str, float]:
    header = response.headers.get("server-timing", "")
    assert header, "expected a Server-Timing header"
    out: dict[str, float] = {}
    for part in header.split(","):
        name, _, dur = part.strip().partition(";dur=")
        out[name] = float(dur)
    return out


@pytest.mark.parametrize(
    "route",
    [
        "/portfolio/summary",
        "/portfolio/holdings?asset_type=MF",
        "/portfolio/allocation?asset_type=MF&by=sector",
        "/portfolio/history",
    ],
)
def test_every_read_reports_total(client: TestClient, route: str) -> None:
    spans = _spans(client.get(route))
    assert spans["total"] >= 0


async def test_cache_hit_summary_reports_cache_and_no_src(
    client: TestClient, db_env
) -> None:
    """With a database, the second summary read is a cache hit: `cache`, no `src`."""
    from db.models import User

    # The cache row is FK'd to `users`; without the row every write misses
    # forever and the second read would re-walk the source.
    async with db_env() as session:
        session.add(User(id="local"))
        await session.commit()

    spans = _spans(client.get("/portfolio/summary"))
    assert "cache" in spans or "src" in spans
    # Second read is served from the read-through cache: no source phase.
    spans = _spans(client.get("/portfolio/summary"))
    assert "cache" in spans
    assert "src" not in spans


def test_holdings_reports_src_on_a_miss(client: TestClient) -> None:
    spans = _spans(client.get("/portfolio/holdings?asset_type=MF"))
    assert "src" in spans


def test_span_names_are_a_closed_set(client: TestClient) -> None:
    spans = _spans(client.get("/portfolio/summary?fresh=1"))
    assert set(spans) <= {"total", "db", "src", "cache"}
