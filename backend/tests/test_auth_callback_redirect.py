"""The OAuth callback lands the browser back on the frontend.

The callback used to render a standalone "you can close this window" page,
written for a popup. Every call site now navigates the current tab (the flow a
user recognises from Google or GitHub), so that page was a dead end on the
*backend* origin with no way back to the app.

Two properties matter here and are easy to regress:

1. **Nothing in the redirect comes from the request.** The origin is server
   configuration, the path is a constant, and `reason` is drawn from a closed
   set. An OAuth callback that redirects to a URL from its own query string is
   an open redirect, and one that echoes a broker error body into a query
   string moves `_auth_html`'s reflected-XSS problem onto the frontend origin.
2. **An unconfigured deployment still works.** Single-tenant local dev has no
   frontend origin to go back to; it must keep rendering the page it always did
   rather than redirect to nowhere.
"""

from __future__ import annotations

from typing import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

from api import main
from api.main import app

FRONTEND = "https://alphadesk.example.in"


@pytest.fixture(autouse=True)
def clear_frontend_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Neither variable is inherited from the developer's shell.

    `_frontend_base_url` falls back to `CORS_ALLOW_ORIGINS`, which a real
    `.env` very plausibly sets — without this the fallback tests would pass or
    fail depending on whose machine ran them.
    """
    monkeypatch.delenv("FRONTEND_BASE_URL", raising=False)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    yield


# --------------------------------------------------------------------------- #
# Where the browser is sent
# --------------------------------------------------------------------------- #
def test_explicit_frontend_base_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_BASE_URL", FRONTEND)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://ignored.example")
    assert main._frontend_base_url() == FRONTEND


def test_falls_back_to_first_cors_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS", f"{FRONTEND},https://second.example"
    )
    assert main._frontend_base_url() == FRONTEND


def test_trailing_slash_does_not_double_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """`https://x/` + `/portfolio` would otherwise be `https://x//portfolio`."""
    monkeypatch.setenv("FRONTEND_BASE_URL", f"{FRONTEND}/")
    assert main._frontend_base_url() == FRONTEND


def test_unconfigured_returns_none() -> None:
    assert main._frontend_base_url() is None


def test_blank_and_whitespace_entries_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", f" , ,  {FRONTEND} ")
    assert main._frontend_base_url() == FRONTEND


# --------------------------------------------------------------------------- #
# What the callback returns
# --------------------------------------------------------------------------- #
def test_success_redirects_to_portfolio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_BASE_URL", FRONTEND)
    response = main._callback_result("IND Money connected.", ok=True)
    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND}/portfolio?ind=connected"


def test_failure_carries_a_reason_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_BASE_URL", FRONTEND)
    response = main._callback_result("nope", reason=main._REASON_STATE)
    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"{FRONTEND}/portfolio?ind=error&reason=state"
    )


def test_unconfigured_still_renders_the_standalone_page() -> None:
    """Local single-tenant dev has no frontend to go home to."""
    response = main._callback_result("IND Money connected.", ok=True)
    assert response.status_code == 200
    assert b"IND Money connected." in response.body


# --------------------------------------------------------------------------- #
# End to end, over HTTP
# --------------------------------------------------------------------------- #
async def _get(path: str) -> object:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_broker_denial_redirects_with_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_BASE_URL", FRONTEND)
    response = await _get("/auth/callback?error=access_denied")
    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"{FRONTEND}/portfolio?ind=error&reason=denied"
    )


async def test_missing_code_redirects_with_missing_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_BASE_URL", FRONTEND)
    response = await _get("/auth/callback?state=abc")
    assert response.status_code == 303
    assert (
        response.headers["location"]
        == f"{FRONTEND}/portfolio?ind=error&reason=missing_params"
    )


async def test_broker_error_text_never_reaches_the_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `error` parameter is attacker-influenced; it must not be echoed.

    `_auth_html` escapes it because it was a reflected XSS on the backend
    origin. A redirect that interpolated it would hand the same string to the
    frontend origin instead — and could break out of the query string entirely.
    """
    payload = "<script>alert(1)</script>&ind=connected"
    monkeypatch.setenv("FRONTEND_BASE_URL", FRONTEND)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/callback", params={"error": payload})
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == f"{FRONTEND}/portfolio?ind=error&reason=denied"
    assert "script" not in location
    # The forged `ind=connected` must not have survived into the query string.
    query = parse_qs(urlsplit(location).query)
    assert query["ind"] == ["error"]


async def test_unconfigured_endpoint_keeps_the_html_page() -> None:
    response = await _get("/auth/callback?error=access_denied")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
