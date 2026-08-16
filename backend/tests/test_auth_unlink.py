"""`POST /auth/unlink` — disconnecting IND Money from the dashboard (issue #13).

Three properties, and they are the ones a user pressing the button is trusting:

1. **It is theirs to press.** JWT-only, exactly like `/auth/login` and
   `/auth/logout` — an anonymous caller has no link to break, and the (dead)
   admin header authenticates nothing.
2. **It actually disconnects.** The grant is revoked at the broker *first*, then
   the `broker_links` row is gone, and the answer says which of the two happened
   — a failed upstream revocation reports `upstream_revoked: false` rather than
   claiming a grant was killed that is still live.
3. **It is idempotent.** A second press, a stale tab, a double-click: a user who
   is already unlinked gets a 200 saying `not_linked`, never a 500.
"""

from __future__ import annotations

from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from api.main import app
from api.routes.portfolio import reset_connector
from db.models import BrokerLink
from services import adoption
from tests.clerk_stub import bearer, clerk, clerk_key  # noqa: F401
from tests.ind_oauth_stub import ISSUER, FakeBroker, broker  # noqa: F401
from tools import ind_money_auth as auth

USER = "user_2unlinkkkkkkkkkkkkkkkkkkkk"
ADMIN = {"x-alphadesk-admin-secret": "test-admin-secret"}
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


async def _link_rows(maker: Any, user_id: str) -> int:
    async with maker() as session:
        result = await session.execute(
            select(BrokerLink.id).where(BrokerLink.user_id == user_id)
        )
        return len(result.scalars().all())


# --------------------------------------------------------------------------- #
# Whose link this is
# --------------------------------------------------------------------------- #
async def test_unlink_rejects_an_anonymous_caller(client: Any) -> None:
    assert (await client.post("/auth/unlink")).status_code == 401


async def test_unlink_rejects_the_admin_header(client: Any) -> None:
    """Unlinking is a per-user act; no operator secret speaks for a user."""
    assert (await client.post("/auth/unlink", headers=ADMIN)).status_code == 401


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #
async def test_unlink_revokes_upstream_then_deletes_the_link(
    db_env: Any, client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    await _link(client, clerk, USER)
    assert await _link_rows(db_env, USER) == 1

    response = await client.post("/auth/unlink", headers=bearer(clerk, USER))

    assert response.status_code == 200
    assert response.json() == {"status": "unlinked", "upstream_revoked": True}
    assert "/revoke" in broker.calls
    assert await _link_rows(db_env, USER) == 0
    status = (await client.get("/auth/status", headers=bearer(clerk, USER))).json()
    assert status["authenticated"] is False


async def test_a_failed_upstream_revocation_still_unlinks_and_says_so(
    db_env: Any, client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    """"We forgot your token" is not "your access is gone" — so the UI is told."""
    await _link(client, clerk, USER)
    broker.revoke_status = 500

    response = await client.post("/auth/unlink", headers=bearer(clerk, USER))

    assert response.status_code == 200
    assert response.json() == {"status": "unlinked", "upstream_revoked": False}
    assert await _link_rows(db_env, USER) == 0


# --------------------------------------------------------------------------- #
# Pressing it twice
# --------------------------------------------------------------------------- #
async def test_unlinking_an_unlinked_user_is_a_200_not_an_error(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    first = await client.post("/auth/unlink", headers=bearer(clerk, USER))
    assert first.status_code == 200
    assert first.json() == {"status": "not_linked", "upstream_revoked": False}


async def test_the_second_press_reports_not_linked(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    await _link(client, clerk, USER)
    assert (await client.post("/auth/unlink", headers=bearer(clerk, USER))).json()[
        "status"
    ] == "unlinked"
    second = await client.post("/auth/unlink", headers=bearer(clerk, USER))
    assert second.status_code == 200
    assert second.json() == {"status": "not_linked", "upstream_revoked": False}


# --------------------------------------------------------------------------- #
# The process keeps nothing
# --------------------------------------------------------------------------- #
async def test_unlink_drops_the_cached_auth_store(
    client: Any, clerk: rsa.RSAPrivateKey, broker: FakeBroker
) -> None:
    """The store caches *decrypted* tokens; a disconnect that leaves it in the
    process has disconnected nothing the next request would notice."""
    await _link(client, clerk, USER)
    assert any(key[0] == USER for key in auth._stores)

    await client.post("/auth/unlink", headers=bearer(clerk, USER))

    assert not any(key[0] == USER for key in auth._stores)
