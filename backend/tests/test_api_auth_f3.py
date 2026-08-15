"""The F3 gates, over HTTP, against the real app and the real database.

`test_ind_money_auth.py` proves the store is per user. This file proves the
*endpoints* are — which is a different claim, and the one an attacker actually
tests. Two signed-in users, one linked and one not, both talking to
`api.main.app` through ASGI.

Three properties are pinned here and nowhere else:

1. **User B cannot observe user A's link.** Not its status, not its holdings,
   not by 403-vs-404 timing — B is simply a user with no link.
2. **`/auth/login` and `/auth/logout` are JWT-only.** The interim C0 admin
   secret opens `/portfolio/*` and nothing else; an admin-header link would be
   an unowned link, which is the exact thing C0 was invented to prevent.
3. **A bad token never falls through to the admin path.** Presenting a rejected
   token and getting an anonymous retry would make the weaker credential the
   effective one.
"""

from __future__ import annotations

from contextlib import suppress
from decimal import Decimal
from typing import Any, Iterator, Optional
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from api.main import app
from api.routes.portfolio import connector_for_request, reset_connector
from portfolio.connectors import StubConnector
from services import adoption
from services import snapshots
from tests.clerk_stub import bearer, clerk, clerk_key  # noqa: F401
from tests.ind_oauth_stub import ISSUER, FakeBroker, broker  # noqa: F401
from tools import ind_money_auth as auth

USER_A = "user_2aaaaaaaaaaaaaaaaaaaaaaaa"
USER_B = "user_2bbbbbbbbbbbbbbbbbbbbbbbb"
ADMIN_SECRET = "test-admin-secret"
ADMIN = {"x-alphadesk-admin-secret": ADMIN_SECRET}
REDIRECT = "http://127.0.0.1:8000/auth/callback"


async def _no_fx() -> Optional[Decimal]:
    """No live FX call from this suite; the rate has its own tests."""
    return None


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ALPHADESK_ADMIN_SECRET", ADMIN_SECRET)
    monkeypatch.setenv("IND_MONEY_MCP_URL", f"{ISSUER}/mcp")
    monkeypatch.setenv("IND_MONEY_AUTH_REDIRECT", REDIRECT)
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    monkeypatch.delenv(adoption.OPERATOR_EMAIL_ENV, raising=False)
    auth.reset_auth_stores()
    auth.reset_discovery()
    adoption.reset_adoption_cache()
    reset_connector()
    yield
    auth.reset_auth_stores()
    auth.reset_discovery()
    adoption.reset_adoption_cache()
    reset_connector()
    app.dependency_overrides.clear()


@pytest.fixture
async def client(db_env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The app over ASGI, with S1's opportunistic capture defanged.

    `/portfolio/summary` fires a background capture when today has no snapshot,
    which is correct behaviour and has its own suite. Left alone here it would
    make every request in this file wait on a live FX call and 1.5s of
    inter-bucket pacing, for a capture none of these assertions are about.
    """
    monkeypatch.setattr(snapshots, "fetch_usd_inr", _no_fx)
    monkeypatch.setattr(snapshots, "CALL_SPACING_SECONDS", 0.0)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        yield http
    for task in list(snapshots._background):
        with suppress(Exception):
            await task


async def _link(client: Any, key: rsa.RSAPrivateKey, user_id: str) -> None:
    """Drive a full login for `user_id` through the real endpoints."""
    started = await client.post("/auth/login", headers=bearer(key, user_id))
    assert started.status_code == 200, started.text
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    landed = await client.get(f"/auth/callback?code=abc&state={state}")
    assert landed.status_code == 200
    assert "IND Money connected." in landed.text


# --------------------------------------------------------------------------- #
# Cross-user isolation
# --------------------------------------------------------------------------- #
async def test_each_user_sees_only_their_own_link_status(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    await _link(client, clerk, USER_A)

    a = (await client.get("/auth/status", headers=bearer(clerk, USER_A))).json()
    b = (await client.get("/auth/status", headers=bearer(clerk, USER_B))).json()

    assert a["authenticated"] is True and a["user_id"] == USER_A
    assert b["authenticated"] is False and b["user_id"] == USER_B


async def test_an_anonymous_caller_learns_nothing_about_anyone(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    """Pre-F3 this endpoint answered for the process, so anyone on the internet
    could read whether the operator was connected. Now it answers for the
    caller, and an anonymous caller is nobody."""
    await _link(client, clerk, USER_A)
    body = (await client.get("/auth/status")).json()
    assert body == {
        "authenticated": False,
        "source": None,
        "expires_at": None,
        "expires_in_sec": None,
        "revoked": False,
        "user_id": None,
    }


async def test_one_user_cannot_unlink_another(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    await _link(client, clerk, USER_A)

    # B has nothing to unlink; the call is about B and only B.
    assert (await client.post("/auth/logout", headers=bearer(clerk, USER_B))).status_code == 200
    assert (
        await client.get("/auth/status", headers=bearer(clerk, USER_A))
    ).json()["authenticated"] is True


async def test_an_unlinked_user_gets_not_linked_not_someone_elses_portfolio(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    """The leak, phrased as a test: B must not receive A's holdings.

    `/portfolio/*` is left on the *real* connector here on purpose — overriding
    it would replace the very thing under test. B has no link, so the connector
    cannot mint a token, so the route answers `not_linked`.
    """
    await _link(client, clerk, USER_A)

    response = await client.get("/portfolio/summary", headers=bearer(clerk, USER_B))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_linked"


async def test_the_summary_names_the_caller(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    body = (await client.get("/portfolio/summary", headers=bearer(clerk, USER_B))).json()
    assert body["user_id"] == USER_B


# --------------------------------------------------------------------------- #
# Linking is JWT-only
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("route", ["/auth/login", "/auth/logout"])
async def test_linking_rejects_the_admin_header(client: Any, route: str) -> None:
    """C0 existed to stop an unowned link. An admin-header link is exactly that."""
    assert (await client.post(route, headers=ADMIN)).status_code == 401


@pytest.mark.parametrize("route", ["/auth/login", "/auth/logout"])
async def test_linking_rejects_an_anonymous_caller(client: Any, route: str) -> None:
    assert (await client.post(route)).status_code == 401


async def test_single_tenant_dev_can_still_link_without_a_token(
    client: Any, broker: FakeBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    started = await client.post("/auth/login")
    assert started.status_code == 200
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    assert (await client.get(f"/auth/callback?code=abc&state={state}")).status_code == 200
    assert (await auth.auth_status(auth.LOCAL_USER_ID))["authenticated"] is True


# --------------------------------------------------------------------------- #
# The interim admin path on /portfolio/*
# --------------------------------------------------------------------------- #
ROUTES = [
    "/portfolio/summary",
    "/portfolio/holdings?asset_type=MF",
    "/portfolio/allocation?asset_type=MF&by=sector",
    "/portfolio/history",
]


@pytest.mark.parametrize("route", ROUTES)
async def test_the_admin_header_still_works_until_l1(client: Any, route: str) -> None:
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    assert (await client.get(route, headers=ADMIN)).status_code == 200


@pytest.mark.parametrize("route", ROUTES)
async def test_a_jwt_works_without_the_admin_header(
    client: Any, clerk: rsa.RSAPrivateKey, route: str
) -> None:
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    assert (await client.get(route, headers=bearer(clerk, USER_A))).status_code == 200


@pytest.mark.parametrize("route", ROUTES)
async def test_neither_credential_is_401(client: Any, route: str) -> None:
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    assert (await client.get(route)).status_code == 401


async def test_a_bad_token_does_not_fall_through_to_the_admin_path(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """Presenting a rejected token *and* the admin secret must not succeed.

    Otherwise the effective credential is whichever of the two is weaker, and
    every future tightening of the token path is decorative.
    """
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    response = await client.get(
        "/portfolio/summary",
        headers={"Authorization": "Bearer not-a-real-token", **ADMIN},
    )
    assert response.status_code == 401


async def test_an_expired_token_does_not_fall_through_either(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    stale = bearer(clerk, USER_A, exp=1)
    response = await client.get("/portfolio/summary", headers={**stale, **ADMIN})
    assert response.status_code == 401


async def test_the_admin_path_acts_as_local_before_adoption(client: Any) -> None:
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    body = (await client.get("/portfolio/summary", headers=ADMIN)).json()
    assert body["user_id"] == auth.LOCAL_USER_ID


async def test_the_admin_path_follows_the_operator_after_adoption(
    client: Any, clerk: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator signs in once; the admin header must keep reaching the same
    data afterwards, or their dashboard empties out on the day identity lands."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, "operator@example.com")
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()

    signed_in = await client.get(
        "/portfolio/summary",
        headers=bearer(clerk, USER_A, email="operator@example.com"),
    )
    assert signed_in.json()["user_id"] == USER_A

    adoption.reset_adoption_cache()
    body = (await client.get("/portfolio/summary", headers=ADMIN)).json()
    assert body["user_id"] == USER_A


# --------------------------------------------------------------------------- #
# The callback trusts the state and nothing else
# --------------------------------------------------------------------------- #
async def test_a_replayed_callback_links_nothing(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    started = await client.post("/auth/login", headers=bearer(clerk, USER_A))
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]

    first = await client.get(f"/auth/callback?code=a&state={state}")
    assert "IND Money connected." in first.text

    replay = await client.get(f"/auth/callback?code=a&state={state}")
    assert replay.status_code == 200
    assert "IND Money connected." not in replay.text
    assert "Nothing was connected" in replay.text


async def test_a_forged_state_links_nothing(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    landed = await client.get("/auth/callback?code=a&state=forged-by-hand")
    assert "Nothing was connected" in landed.text
    assert (
        await client.get("/auth/status", headers=bearer(clerk, USER_A))
    ).json()["authenticated"] is False


async def test_the_callback_error_page_never_echoes_the_broker(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    """A token-endpoint error body can quote payload fragments; this page is
    rendered to whoever happens to land on the callback."""
    started = await client.post("/auth/login", headers=bearer(clerk, USER_A))
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    broker.token_status = 400

    landed = await client.get(f"/auth/callback?code=a&state={state}")
    assert "nope" not in landed.text
    assert "400" not in landed.text
