"""Request rate limits on the expensive surfaces (card L1).

The middleware answers **429** past two ceilings — a per-caller cap and a global
cap — on `/analyze`, `/portfolio/overview` and `/auth/login`. This is the
request-rate limit; it is distinct from the overview's daily *spend* cap
(`test_overview_api.py::test_overview_over_spend_cap_degrades`), which degrades
rather than erroring because A1 forbids an error there.

Every request here is stopped **at the middleware**, before any auth or DB work,
so the tests need no database and no token: a guarded path with the caps set low
429s on its own.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.ratelimit import GUARDED_PATHS, reset_rate_limits


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # A generous window so a whole test lands inside one bucket.
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "3600")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _post(client: TestClient, path: str, **kw):
    # A GET on /portfolio/overview is a 405, but the limiter runs first, so for
    # counting we hit the real method each endpoint takes.
    return client.post(path, **kw)


def test_per_caller_cap_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past the per-caller ceiling, the same caller gets 429 with Retry-After."""
    monkeypatch.setenv("RATE_LIMIT_PER_CALLER_MAX", "3")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_MAX", "1000")

    seen_429 = False
    for _ in range(10):
        resp = _post(client, "/auth/login")
        if resp.status_code == 429:
            seen_429 = True
            assert resp.json()["detail"]["code"] == "rate_limited"
            assert int(resp.headers["retry-after"]) >= 1
            break
        # Below the cap the request passes the limiter (and then 401s on auth —
        # the point is it was *not* a 429).
        assert resp.status_code != 429
    assert seen_429, "the per-caller cap never tripped"


def test_global_cap_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The global ceiling trips even across distinct callers (distinct tokens)."""
    monkeypatch.setenv("RATE_LIMIT_PER_CALLER_MAX", "1000")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_MAX", "3")

    seen_429 = False
    for i in range(10):
        # A different bearer per request → a different per-caller key, so only
        # the *global* cap can stop these.
        resp = _post(client, "/auth/login", headers={"Authorization": f"Bearer tok-{i}"})
        if resp.status_code == 429:
            seen_429 = True
            break
    assert seen_429, "the global cap never tripped"


def test_unguarded_paths_are_never_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path outside the guarded set is untouched no matter how low the cap."""
    monkeypatch.setenv("RATE_LIMIT_PER_CALLER_MAX", "1")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_MAX", "1")
    for _ in range(20):
        assert client.get("/").status_code == 200


def test_the_limiter_can_be_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("RATE_LIMIT_PER_CALLER_MAX", "1")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_MAX", "1")
    for _ in range(10):
        # No 429 — every one reaches the endpoint (and 401s on missing auth).
        assert _post(client, "/auth/login").status_code != 429


def test_429_carries_cors_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cross-origin 429 must still carry `Access-Control-Allow-Origin`.

    CORS is the **outermost** middleware (added last), so it wraps the limiter's
    429 on the way out. If it did not — if the limiter sat outside CORS — a
    browser would receive the 429 with no CORS header and surface it as an opaque
    network error instead of the 429 + `Retry-After` we sent.
    """
    monkeypatch.setenv("RATE_LIMIT_PER_CALLER_MAX", "1")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_MAX", "1000")
    origin = "http://localhost:3000"

    seen = None
    for _ in range(5):
        resp = _post(client, "/auth/login", headers={"Origin": origin})
        if resp.status_code == 429:
            seen = resp
            break
    assert seen is not None, "the per-caller cap never tripped"
    assert seen.headers.get("access-control-allow-origin") == origin


def test_options_is_exempt_from_the_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A preflight must not burn a slot — otherwise N real calls cost 2N.

    A plain `OPTIONS` (no CORS-preflight headers) passes through CORS to the
    limiter, which exempts it: any number of them never 429s, and the one real
    slot the cap allows is still there afterward.
    """
    monkeypatch.setenv("RATE_LIMIT_PER_CALLER_MAX", "1")
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_MAX", "1")

    for _ in range(10):
        assert client.options("/auth/login").status_code != 429
    # The single allowed request still gets through — the OPTIONS did not count.
    assert _post(client, "/auth/login").status_code != 429


def test_all_three_expensive_surfaces_are_guarded() -> None:
    assert set(GUARDED_PATHS) == {"/analyze", "/portfolio/overview", "/auth/login"}
