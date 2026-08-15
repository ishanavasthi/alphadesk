"""Per-user IND Money linking (card F3).

The IND Money endpoints are **mocked** here — discovery, dynamic client
registration, the token endpoint and revocation — because every one of them has
a side effect on a real broker account: `/register` mints a live OAuth client,
`/token` burns a one-use code, `/revoke` kills a grant the operator would have
to re-establish by hand. What is not mocked is anything of ours: the tokens go
through real Fernet into a real Postgres, the state rows are real rows, and the
single-use rule is enforced by a real `DELETE ... RETURNING`.

The assertions that matter most are the negative ones. "User B cannot see user
A's link" and "a replayed `state` links nothing" are the properties this card
exists to establish, and they are the ones a future refactor is most likely to
lose quietly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select, text

from cryptography.fernet import Fernet

from db.crypto import decrypt
from db.models import BrokerLink, OAuthPending, utcnow
from tests.ind_oauth_stub import DISCOVERY, ISSUER, FakeBroker, broker  # noqa: F401
from tools import ind_money_auth as auth

# `asyncio_mode = auto` (pytest.ini) runs the async tests below; the sync ones
# are pure-function checks that need no loop.

USER_A = "user_2aaaaaaaaaaaaaaaaaaaaaaaa"
USER_B = "user_2bbbbbbbbbbbbbbbbbbbbbbbb"
REDIRECT = "http://127.0.0.1:8000/auth/callback"

@pytest.fixture(autouse=True)
def clean_auth_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No process-global credential, discovery or store survives a test."""
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    monkeypatch.delenv("IND_MONEY_MCP_TOKEN", raising=False)
    monkeypatch.delenv("IND_MONEY_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("IND_MONEY_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("IND_MONEY_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("IND_MONEY_OAUTH_SCOPE", raising=False)
    monkeypatch.setenv("IND_MONEY_MCP_URL", f"{ISSUER}/mcp")
    auth.reset_auth_stores()
    auth.reset_discovery()
    auth._PENDING_DEV.clear()
    yield
    auth.reset_auth_stores()
    auth.reset_discovery()
    auth._PENDING_DEV.clear()


async def _link(user_id: str, redirect: str = REDIRECT) -> str:
    """Run a whole login for `user_id` and return the authorization URL used."""
    url = await auth.begin_login(user_id, redirect)
    state = parse_qs(urlsplit(url).query)["state"][0]
    await auth.complete_login("code-123", state)
    return url


async def _row(maker: Any, user_id: str) -> BrokerLink | None:
    async with maker() as session:
        result = await session.execute(
            select(BrokerLink).where(BrokerLink.user_id == user_id)
        )
        return result.scalars().first()


# --------------------------------------------------------------------------- #
# Encryption at rest
# --------------------------------------------------------------------------- #
async def test_no_token_is_stored_in_the_clear(db_env: Any, broker: FakeBroker) -> None:
    """The raw column must never contain the token. Checked in SQL, not the ORM.

    Asserting through `decrypt()` would only prove the round-trip works; it is
    the *ciphertext* that has to be unreadable, so this reads the column as text
    and looks for the plaintext in it.
    """
    broker.access, broker.refresh = "plaintext-access-xyz", "plaintext-refresh-xyz"
    await _link(USER_A)

    async with db_env() as session:
        row = (
            await session.execute(
                text(
                    "SELECT access_token_enc, refresh_token_enc, client_secret_enc "
                    "FROM broker_links WHERE user_id = :u"
                ),
                {"u": USER_A},
            )
        ).one()

    blob = " ".join(row)
    assert "plaintext-access-xyz" not in blob
    assert "plaintext-refresh-xyz" not in blob
    assert "sec-1" not in blob
    assert decrypt(row[0]) == "plaintext-access-xyz"
    assert decrypt(row[1]) == "plaintext-refresh-xyz"
    assert decrypt(row[2]) == "sec-1"


# --------------------------------------------------------------------------- #
# State binding: single use, TTL, and an owner the caller cannot choose
# --------------------------------------------------------------------------- #
async def test_state_is_single_use(db_env: Any, broker: FakeBroker) -> None:
    url = await auth.begin_login(USER_A, REDIRECT)
    state = parse_qs(urlsplit(url).query)["state"][0]

    assert await auth.complete_login("code-1", state) == USER_A
    with pytest.raises(auth.OAuthStateError):
        await auth.complete_login("code-1", state)


async def test_expired_state_links_nothing(db_env: Any, broker: FakeBroker) -> None:
    url = await auth.begin_login(USER_A, REDIRECT)
    state = parse_qs(urlsplit(url).query)["state"][0]

    async with db_env() as session:
        await session.execute(
            text("UPDATE oauth_pending SET created_at = :t WHERE state = :s"),
            {
                "t": utcnow() - timedelta(seconds=auth.STATE_TTL_SECONDS + 60),
                "s": state,
            },
        )
        await session.commit()

    with pytest.raises(auth.OAuthStateError):
        await auth.complete_login("code-1", state)
    assert await _row(db_env, USER_A) is None
    # And the row is gone, so a *fresh* clock cannot resurrect it either.
    async with db_env() as session:
        assert (await session.execute(select(OAuthPending))).first() is None


async def test_the_callback_links_the_state_owner(db_env: Any, broker: FakeBroker) -> None:
    """The owner comes off the row. There is nothing else it could come from."""
    url = await auth.begin_login(USER_A, REDIRECT)
    state = parse_qs(urlsplit(url).query)["state"][0]

    assert await auth.complete_login("code-1", state) == USER_A
    assert await _row(db_env, USER_A) is not None
    assert await _row(db_env, USER_B) is None


async def test_unknown_state_links_nothing(db_env: Any, broker: FakeBroker) -> None:
    with pytest.raises(auth.OAuthStateError):
        await auth.complete_login("code-1", "never-issued")
    assert await _row(db_env, USER_A) is None


async def test_purge_expired_pending_leaves_fresh_rows(
    db_env: Any, broker: FakeBroker
) -> None:
    await auth.begin_login(USER_A, REDIRECT)
    stale = await auth.begin_login(USER_B, REDIRECT)
    stale_state = parse_qs(urlsplit(stale).query)["state"][0]
    async with db_env() as session:
        await session.execute(
            text("UPDATE oauth_pending SET created_at = :t WHERE state = :s"),
            {"t": utcnow() - timedelta(hours=2), "s": stale_state},
        )
        await session.commit()

    assert await auth.purge_expired_pending() == 1
    async with db_env() as session:
        remaining = (await session.execute(select(OAuthPending.user_id))).scalars().all()
    assert remaining == [USER_A]


# --------------------------------------------------------------------------- #
# Cross-user isolation
# --------------------------------------------------------------------------- #
async def test_one_users_link_does_not_authenticate_another(
    db_env: Any, broker: FakeBroker
) -> None:
    await _link(USER_A)

    assert (await auth.auth_status(USER_A))["authenticated"] is True
    b_status = await auth.auth_status(USER_B)
    assert b_status["authenticated"] is False
    assert b_status["user_id"] == USER_B

    with pytest.raises(auth.MCPAuthInvalid):
        await auth.get_access_token(USER_B)


async def test_unlinking_one_user_leaves_the_other_linked(
    db_env: Any, broker: FakeBroker
) -> None:
    await _link(USER_A)
    await _link(USER_B)

    await auth.logout(USER_A)

    assert await _row(db_env, USER_A) is None
    assert await _row(db_env, USER_B) is not None
    assert (await auth.auth_status(USER_B))["authenticated"] is True


# --------------------------------------------------------------------------- #
# Locking
# --------------------------------------------------------------------------- #
async def test_locks_are_per_user_not_global() -> None:
    a = auth._lock_for((USER_A, auth.SOURCE))
    b = auth._lock_for((USER_B, auth.SOURCE))
    assert a is not b
    assert auth._lock_for((USER_A, auth.SOURCE)) is a


async def test_one_users_refresh_does_not_block_another(
    db_env: Any, broker: FakeBroker
) -> None:
    """A slow refresh for A must not hold B's request hostage.

    Pinned by ordering rather than by wall-clock: B's token has to come back
    while A is still parked inside its own lock, which a shared lock makes
    impossible.
    """
    await _link(USER_A)
    await _link(USER_B)

    order: list[str] = []
    a_inside = asyncio.Event()
    release_a = asyncio.Event()

    store_a = auth.AuthStore.for_user(USER_A)
    store_b = auth.AuthStore.for_user(USER_B)
    # Force both to look expired so `get_token` takes the refresh path.
    store_a._expires_at = 0.0
    store_b._expires_at = 0.0

    async def slow_refresh() -> str:
        a_inside.set()
        await release_a.wait()
        order.append("a-refreshed")
        return "acc-a"

    async def fast_refresh() -> str:
        order.append("b-refreshed")
        return "acc-b"

    store_a._refresh_token = slow_refresh  # type: ignore[method-assign]
    store_b._refresh_token = fast_refresh  # type: ignore[method-assign]

    task_a = asyncio.create_task(store_a.get_token())
    await a_inside.wait()
    assert await store_b.get_token() == "acc-b"
    release_a.set()
    assert await task_a == "acc-a"
    assert order == ["b-refreshed", "a-refreshed"]


async def test_concurrent_calls_for_one_user_refresh_once(
    db_env: Any, broker: FakeBroker
) -> None:
    await _link(USER_A)
    store = auth.AuthStore.for_user(USER_A)
    store._expires_at = 0.0

    refreshes = 0
    original = store._refresh_token

    async def counting() -> str:
        nonlocal refreshes
        refreshes += 1
        await asyncio.sleep(0)
        return await original()

    store._refresh_token = counting  # type: ignore[method-assign]
    await asyncio.gather(*(store.get_token() for _ in range(5)))
    assert refreshes == 1


# --------------------------------------------------------------------------- #
# Unlink: revoke, then delete
# --------------------------------------------------------------------------- #
async def test_logout_revokes_upstream_before_deleting(
    db_env: Any, broker: FakeBroker
) -> None:
    """**Ordering**, not just "both happened".

    The first version of this test asserted a revoke call and an absent row,
    which is satisfied just as well by deleting first and revoking after — and
    "we deleted our copy" is not "your access is gone". So the two events are
    recorded on one list: the broker hook fires when `/revoke` is hit, and the
    local invalidation is wrapped to record itself. Moving `_invalidate` above
    `revoke_token` in `AuthStore.logout` flips the list and fails here.
    """
    await _link(USER_A)
    broker.calls.clear()

    order: list[str] = []
    store = auth.AuthStore.for_user(USER_A)
    await store.ensure_loaded()
    broker.on_revoke = lambda: order.append("revoke")
    real_invalidate = store._invalidate

    async def recording_invalidate(**kwargs: Any) -> None:
        order.append("delete")
        await real_invalidate(**kwargs)

    store._invalidate = recording_invalidate  # type: ignore[method-assign]

    result = await store.logout()

    assert order == ["revoke", "delete"], (
        "the grant must be killed at the source before the local row goes"
    )
    assert result["revoked_upstream"] is True
    assert await _row(db_env, USER_A) is None


async def test_logout_still_unlinks_when_revocation_fails(
    db_env: Any, broker: FakeBroker
) -> None:
    """The user asked to be unlinked. An upstream failure is reported, not obeyed."""
    await _link(USER_A)
    broker.revoke_status = 500

    result = await auth.logout(USER_A)

    assert result["revoked_upstream"] is False
    assert result["revocation_error"]
    assert await _row(db_env, USER_A) is None


# --------------------------------------------------------------------------- #
# Client registration and scopes
# --------------------------------------------------------------------------- #
async def test_the_registered_client_is_reused_on_relink(
    db_env: Any, broker: FakeBroker
) -> None:
    await _link(USER_A)
    assert broker.registrations == 1
    await _link(USER_A)
    assert broker.registrations == 1, "a re-link must not mint a second client"


async def test_a_moved_redirect_uri_forces_a_new_client(
    db_env: Any, broker: FakeBroker
) -> None:
    """DCR binds a client to its redirect_uris, so a moved callback needs a new one."""
    await _link(USER_A)
    await _link(USER_A, redirect="https://backend.example/auth/callback")
    assert broker.registrations == 2


async def test_each_user_gets_their_own_client(db_env: Any, broker: FakeBroker) -> None:
    await _link(USER_A)
    await _link(USER_B)
    assert broker.registrations == 2
    a, b = await _row(db_env, USER_A), await _row(db_env, USER_B)
    assert a is not None and b is not None
    assert a.client_id != b.client_id


async def test_both_scopes_are_requested(db_env: Any, broker: FakeBroker) -> None:
    """C2 verified `scopes_supported = [portfolio:read, market:read]`; ask for both."""
    url = await auth.begin_login(USER_A, REDIRECT)
    scope = parse_qs(urlsplit(url).query)["scope"][0]
    assert set(scope.split()) == {"portfolio:read", "market:read"}


async def test_the_authorization_url_carries_pkce(db_env: Any, broker: FakeBroker) -> None:
    query = parse_qs(urlsplit(await auth.begin_login(USER_A, REDIRECT)).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    async with db_env() as session:
        verifier = (await session.execute(select(OAuthPending.verifier))).scalars().one()
    assert verifier not in query["code_challenge"][0], "the challenge is not the verifier"


# --------------------------------------------------------------------------- #
# Revocation is reported, not swallowed (the M1/S1 carry)
# --------------------------------------------------------------------------- #
async def test_a_definitively_rejected_refresh_reports_revoked(
    db_env: Any, broker: FakeBroker
) -> None:
    await _link(USER_A)
    store = auth.AuthStore.for_user(USER_A)
    store._expires_at = 0.0
    broker.token_status = 400  # invalid_grant: the refresh token is dead

    status = await store.status_verified()

    assert status["authenticated"] is False
    assert status["revoked"] is True, (
        "an idle status poll has to be able to reach REVOKED; flattening this "
        "into a plain False is what made link_health say 'needs relink' forever"
    )
    row = await _row(db_env, USER_A)
    assert row is not None and row.status == "revoked"


async def test_a_transient_refresh_failure_is_not_revocation(
    db_env: Any, broker: FakeBroker
) -> None:
    await _link(USER_A)
    store = auth.AuthStore.for_user(USER_A)
    store._expires_at = 0.0
    broker.token_status = 503

    status = await store.status_verified()

    assert status["authenticated"] is False
    assert status["revoked"] is False
    row = await _row(db_env, USER_A)
    assert row is not None and row.status == "active", "credentials survive a 5xx"


# --------------------------------------------------------------------------- #
# The ambient credential sources are single-tenant dev only
# --------------------------------------------------------------------------- #
async def test_env_and_file_authenticate_nobody_outside_single_tenant(
    db_env: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The security fix, stated as a test.

    Every ambient source is present and pointed at a valid-looking credential.
    With `ALPHADESK_SINGLE_TENANT` unset, none of them may authenticate anyone —
    not the `"local"` id they were written for, and certainly not a Clerk user.
    """
    cache = tmp_path / ".ind_money_token.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "operator-access",
                "refresh_token": "operator-refresh",
                "expires_at": 9999999999,
                "client_id": "operator-client",
            }
        )
    )
    monkeypatch.setattr(auth, "_CACHE_FILE", cache)
    monkeypatch.setenv("IND_MONEY_MCP_TOKEN", "static-operator-bearer")
    monkeypatch.setenv("IND_MONEY_OAUTH_CLIENT_ID", "env-client")
    monkeypatch.setenv("IND_MONEY_OAUTH_REFRESH_TOKEN", "env-refresh")

    for user in (auth.LOCAL_USER_ID, USER_A):
        status = await auth.AuthStore.for_user(user).status_verified()
        assert status["authenticated"] is False, user


async def test_single_tenant_dev_still_hydrates_local_from_the_file(
    db_env: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The operator's existing dev setup keeps working — for `"local"` only."""
    cache = tmp_path / ".ind_money_token.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "operator-access",
                "refresh_token": "operator-refresh",
                "expires_at": 9999999999.0,
                "client_id": "operator-client",
            }
        )
    )
    monkeypatch.setattr(auth, "_CACHE_FILE", cache)
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")

    assert (await auth.AuthStore.for_user(auth.LOCAL_USER_ID).status_verified())[
        "authenticated"
    ] is True
    assert (await auth.AuthStore.for_user(USER_A).status_verified())[
        "authenticated"
    ] is False, "single-tenant mode is not a licence to serve the file to a real user"


async def test_a_db_row_wins_over_the_dev_file(
    db_env: Any, broker: FakeBroker, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    cache = tmp_path / ".ind_money_token.json"
    cache.write_text(json.dumps({"access_token": "stale", "expires_at": 9999999999.0}))
    monkeypatch.setattr(auth, "_CACHE_FILE", cache)
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    broker.access = "fresh-from-db"

    await _link(auth.LOCAL_USER_ID)
    auth.reset_auth_stores()
    assert await auth.get_access_token(auth.LOCAL_USER_ID) == "fresh-from-db"


# --------------------------------------------------------------------------- #
# A link row the server can no longer decrypt
# --------------------------------------------------------------------------- #
async def test_a_rotated_encryption_key_is_needs_relink_not_a_500(
    db_env: Any, broker: FakeBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`TOKEN_ENCRYPTION_KEY` is an env var on a Space anyone can edit.

    Rotating or losing it makes every stored credential unreadable — a real
    operational state, and one that used to escape as a bare `RuntimeError` out
    of `/auth/status`, `/auth/login`, `/auth/logout` and all of `/portfolio/*`,
    i.e. a 500. It is not a 500: the link is intact at the source and the
    request is fine, we simply cannot read what we stored. Re-linking fixes it.
    """
    await _link(USER_A)
    auth.reset_auth_stores()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    status = await auth.auth_status(USER_A)

    assert status["authenticated"] is False
    assert status["undecryptable"] is True
    assert status["revoked"] is False, "nobody revoked anything"
    # And the row is left alone, so restoring the old key restores the link.
    assert await _row(db_env, USER_A) is not None


async def test_an_undecryptable_link_reports_needs_relink(
    db_env: Any, broker: FakeBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    from portfolio.connectors import IndMoneyConnector
    from portfolio.models import LinkHealth

    await _link(USER_A)
    auth.reset_auth_stores()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    async def _unused_transport(_tool: str, _args: Any) -> Any:  # pragma: no cover
        raise AssertionError("link_health must not make a source call")

    # An explicit transport keeps `_default_transport` — and its lazy import of
    # the MCP client, which cannot be imported while `httpx.AsyncClient` is
    # monkeypatched — out of this test. The auth store is still the real one.
    connector = IndMoneyConnector(user_id=USER_A, transport=_unused_transport)
    assert await connector.link_health(USER_A) is LinkHealth.NEEDS_RELINK


async def test_relinking_repairs_an_undecryptable_row(
    db_env: Any, broker: FakeBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The advertised fix has to actually work."""
    await _link(USER_A)
    auth.reset_auth_stores()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert (await auth.auth_status(USER_A))["authenticated"] is False

    broker.access = "fresh-after-relink"
    await _link(USER_A)
    assert (await auth.auth_status(USER_A))["authenticated"] is True
    assert await auth.get_access_token(USER_A) == "fresh-after-relink"


async def test_logout_works_on_an_undecryptable_row(
    db_env: Any, broker: FakeBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlinking must not need the key that was lost."""
    await _link(USER_A)
    auth.reset_auth_stores()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    result = await auth.logout(USER_A)

    assert result["authenticated"] is False
    assert await _row(db_env, USER_A) is None


async def test_no_encryption_key_is_reported_not_crashed(
    db_env: Any, broker: FakeBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server with no key at all must refuse to link, in words.

    It refuses at `/auth/login` — the earliest point, because the pending row
    already carries an encrypted client secret — rather than after the user has
    been round-tripped through the broker and spent a one-use code.
    """
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)

    with pytest.raises(auth.MCPAuthError) as excinfo:
        await auth.begin_login(USER_A, REDIRECT)
    assert "TOKEN_ENCRYPTION_KEY" in str(excinfo.value)
    assert await _row(db_env, USER_A) is None


# --------------------------------------------------------------------------- #
# A stored client the server has stopped accepting
# --------------------------------------------------------------------------- #
async def test_a_rejected_client_is_forgotten_and_re_registered(
    db_env: Any, broker: FakeBroker
) -> None:
    """The recovery half of client reuse — and the live failure mode.

    Reusing a registered client is right until the vendor stops accepting it.
    Without this, the same dead `client_id` is loaded from the row on every
    attempt and every login fails identically, forever, with no way out but
    editing the database.
    """
    await _link(USER_A)
    assert broker.registrations == 1

    broker.token_status = 401
    broker.token_body = {"error": "invalid_client"}
    url = await auth.begin_login(USER_A, REDIRECT)
    state = parse_qs(urlsplit(url).query)["state"][0]
    with pytest.raises(auth.MCPAuthError):
        await auth.complete_login("code-2", state)

    row = await _row(db_env, USER_A)
    assert row is not None and row.client_id is None, "the dead client is cleared"

    # And the next attempt registers a new one and succeeds.
    broker.token_status = 200
    broker.token_body = None
    await _link(USER_A)
    assert broker.registrations == 2
    assert (await auth.auth_status(USER_A))["authenticated"] is True


async def test_a_rejected_client_on_refresh_is_forgotten_too(
    db_env: Any, broker: FakeBroker
) -> None:
    await _link(USER_A)
    store = auth.AuthStore.for_user(USER_A)
    store._expires_at = 0.0
    broker.token_status = 400
    broker.token_body = {"error": "invalid_client"}

    with pytest.raises(auth.MCPAuthInvalid):
        await store.get_token()

    row = await _row(db_env, USER_A)
    assert row is not None and row.client_id is None


async def test_a_bad_grant_does_not_forget_the_client(
    db_env: Any, broker: FakeBroker
) -> None:
    """`invalid_grant` is about the token, not the registration.

    Clearing the client here would throw away a perfectly good registration on
    the most ordinary failure there is — an expired refresh token.
    """
    await _link(USER_A)
    store = auth.AuthStore.for_user(USER_A)
    store._expires_at = 0.0
    broker.token_status = 400
    broker.token_body = {"error": "invalid_grant"}

    with pytest.raises(auth.MCPAuthInvalid):
        await store.get_token()

    row = await _row(db_env, USER_A)
    assert row is not None and row.client_id == "cli-1"


# --------------------------------------------------------------------------- #
# Cache bounds
# --------------------------------------------------------------------------- #
async def test_the_store_cache_is_bounded(db_env: Any) -> None:
    """Both caches hold **decrypted** tokens, so unbounded growth is a growing
    pile of plaintext credentials in a process that can stay up for weeks."""
    for index in range(auth._CACHE_MAX + 5):
        auth.AuthStore.for_user(f"user_{index}")
    assert len(auth._stores) <= auth._CACHE_MAX
    assert len(auth._locks) <= auth._CACHE_MAX
