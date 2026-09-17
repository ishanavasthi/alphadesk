"""Relinking after a revocation actually reconnects (issue #80).

The live symptom: revoke IND Money access, log in again, and the dashboard
loads fresh numbers while the top-bar chip still says "access revoked" — and
no amount of Refreshing clears it.

Two process-level memories caused it, and the OAuth callback cleared neither:

1. The cached per-user `IndMoneyConnector` holds a sticky `_revoked` flag from
   the dead grant, and `link_health()` trusts it without re-verifying — so the
   summary pairs fresh holdings with a stale revoked health.
2. The summary cache stores `link_health` inside the payload, so even a healed
   connector would keep serving the old verdict until the TTL lapsed.

The callback now evicts the connector and invalidates the user's cache rows —
mirroring what the unlink endpoint already does.
"""

from __future__ import annotations

from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from api.main import app
from api.routes.portfolio import get_connector, reset_connector
from portfolio.models import LinkHealth
from services import adoption, portfolio_cache
from tests.clerk_stub import bearer, clerk, clerk_key  # noqa: F401
from tests.ind_oauth_stub import ISSUER, FakeBroker, broker  # noqa: F401
from tools import ind_money_auth as auth

USER = "user_2relinkkkkkkkkkkkkkkkkkkkk"
REDIRECT = "http://127.0.0.1:8000/auth/callback"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
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
async def client(db_env: Any) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        yield http


async def _link(client: Any, key: rsa.RSAPrivateKey, user_id: str) -> None:
    """Drive a full login for `user_id` through the real endpoints."""
    started = await client.post("/auth/login", headers=bearer(key, user_id))
    assert started.status_code == 200, started.text
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    landed = await client.get(f"/auth/callback?code=abc&state={state}")
    assert landed.status_code == 200


# --------------------------------------------------------------------------- #
# The revoked memory does not survive a relink
# --------------------------------------------------------------------------- #
async def test_relink_evicts_a_connector_remembering_revocation(
    db_env: Any, client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    await _link(client, clerk, USER)
    old = get_connector(USER)
    old.mark_revoked()
    assert await old.link_health(USER) is LinkHealth.REVOKED

    await _link(client, clerk, USER)

    new = get_connector(USER)
    assert new is not old
    assert await new.link_health(USER) is LinkHealth.LINKED


async def test_relink_invalidates_the_users_cached_summary(
    db_env: Any, client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    await _link(client, clerk, USER)
    async with db_env() as session:
        await portfolio_cache.put(
            session, USER, portfolio_cache.summary_key(), {"link_health": "revoked"}
        )
    async with db_env() as session:
        assert (
            await portfolio_cache.get(session, USER, portfolio_cache.summary_key())
            is not None
        )

    await _link(client, clerk, USER)

    async with db_env() as session:
        assert (
            await portfolio_cache.get(session, USER, portfolio_cache.summary_key())
            is None
        )
