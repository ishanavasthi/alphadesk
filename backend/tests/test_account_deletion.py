"""`DELETE /account` — the delete-my-data cascade (card L1, the centerpiece).

The acceptance that cannot be retrofitted once real user data exists: a user with
a row in **every** table is deleted, the broker token is **revoked upstream**,
and **zero rows survive anywhere** — the database cascade and the in-memory
purge together. A row left behind in any table is a defect this test exists to
catch before it can happen for real.

The exhaustiveness is deliberate: the test seeds `users`, `broker_links`,
`oauth_pending`, `snapshot_days`, `snapshot_holdings`, `snapshot_raw`,
`watchlist` and `portfolio_cache` — the whole schema (V2_PLAN §6, issue #15) —
plus the Lab's in-memory registries
and the no-database watchlist fallback, then asserts each is empty for the user
afterward.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from agents.portfolio.spend import get_limiter
from api import deps
from api.main import _ACTIONS, _ANALYSES, _PAPER_WATCHLIST, _RUNS, app
from db import crypto
from db.models import (
    BrokerLink,
    OAuthPending,
    PortfolioCache,
    SnapshotDay,
    SnapshotHolding,
    SnapshotRaw,
    User,
    Watchlist,
)
from services import adoption
from tests.clerk_stub import bearer, clerk, clerk_key  # noqa: F401
from tools import ind_money_auth as auth

USER = "user_2deleteeeeeeeeeeeeeeeeeeeee"

#: Every table that carries user-owned rows, so "zero rows survive" is checked
#: exhaustively rather than for the handful someone remembered.
ALL_MODELS = (
    User,
    BrokerLink,
    OAuthPending,
    SnapshotDay,
    SnapshotHolding,
    SnapshotRaw,
    Watchlist,
    PortfolioCache,
)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    monkeypatch.delenv(adoption.OPERATOR_EMAIL_ENV, raising=False)
    auth.reset_auth_stores()
    auth.reset_discovery()
    adoption.reset_adoption_cache()
    get_limiter().reset()
    _RUNS.clear()
    _ANALYSES.clear()
    _ACTIONS.clear()
    _PAPER_WATCHLIST.clear()
    yield
    auth.reset_auth_stores()
    adoption.reset_adoption_cache()
    _RUNS.clear()
    _ANALYSES.clear()
    _ACTIONS.clear()
    _PAPER_WATCHLIST.clear()
    app.dependency_overrides.clear()


@pytest.fixture
async def client(db_env: Any) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        yield http


async def _seed_every_table(maker: Any) -> None:
    """Give ``USER`` a row in every table the schema has."""
    async with maker() as session:
        session.add(User(id=USER, email="deleteme@example.com", created_at=_now()))
        await session.flush()  # the parent row must exist before its FK children
        session.add(
            BrokerLink(
                user_id=USER,
                source="ind_money",
                access_token_enc=crypto.encrypt("access-token"),
                refresh_token_enc=crypto.encrypt("refresh-token"),
                client_id="client-123",
                client_secret_enc=crypto.encrypt("client-secret"),
                token_url="https://broker.example/token",
                redirect_uri="https://backend.example/auth/callback",
                supports_refresh=True,
            )
        )
        session.add(
            OAuthPending(
                state="pending-state",
                user_id=USER,
                source="ind_money",
                verifier="pkce-verifier",
                redirect_uri="https://backend.example/auth/callback",
            )
        )
        day = SnapshotDay(
            user_id=USER,
            captured_on=date(2026, 8, 15),
            total_value=Decimal("1234567.89"),
            currency="INR",
        )
        session.add(day)
        await session.flush()  # assign day.id for the children
        session.add(
            SnapshotHolding(
                snapshot_id=day.id,
                source="ind_money",
                external_id="INE-DEMO-01",
                asset_type="IND_STOCK",
                symbol="DEMO",
                current_value=Decimal("1000.00"),
                currency="INR",
            )
        )
        session.add(
            SnapshotRaw(snapshot_id=day.id, source="ind_money", payload={"kind": "snapshot"})
        )
        session.add(
            Watchlist(
                user_id=USER,
                symbol="DEMOSTOCK",
                company="Demo Ltd",
                thesis="a decision record",
                action="buy",
                run_id="run-abc",
                added_at=_now(),
            )
        )
        session.add(
            PortfolioCache(
                user_id=USER,
                cache_key="summary",
                payload={"net_worth": "1234567.89"},
                as_of=_now(),
                fetched_at=_now(),
            )
        )
        await session.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _row_counts(maker: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with maker() as session:
        for model in ALL_MODELS:
            total = await session.execute(select(func.count()).select_from(model))
            counts[model.__tablename__] = int(total.scalar_one())
    return counts


async def test_delete_account_removes_every_row_and_revokes_upstream(
    client: Any,
    db_env: Any,
    clerk: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The centerpiece: every table empty afterward, and revocation was called."""
    await _seed_every_table(db_env)

    # Seed the in-memory Lab state too — the DB cascade cannot reach it.
    _RUNS["run-abc"] = {"user_id": USER, "query": "x", "status": "completed", "action_id": "act-1"}
    _ANALYSES["run-abc"] = {"user_id": USER, "run_id": "run-abc"}
    _ACTIONS["act-1"] = "run-abc"
    _PAPER_WATCHLIST[USER] = {"DEMOSTOCK": {"symbol": "DEMOSTOCK"}}

    # And the overview spend tally — a per-user cache the DB cascade cannot reach.
    get_limiter().reserve(USER)
    assert USER in get_limiter()._per_user

    # Record that upstream revocation was called, without a real broker.
    revoked_with: list[str] = []

    async def _fake_revoke(token: str, client_id: Any, client_secret: Any) -> bool:
        revoked_with.append(token)
        return True

    monkeypatch.setattr(auth, "revoke_token", _fake_revoke)

    # Every table starts non-empty.
    before = await _row_counts(db_env)
    assert all(n >= 1 for n in before.values()), before

    response = await client.request("DELETE", "/account", headers=bearer(clerk, USER))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["user_id"] == USER
    assert body["revoked_upstream"] is True

    # 1. Upstream revocation happened, with the decrypted refresh token.
    assert revoked_with == ["refresh-token"]

    # 2. Zero rows survive in EVERY table — the acceptance centerpiece.
    after = await _row_counts(db_env)
    assert after == {m.__tablename__: 0 for m in ALL_MODELS}, after

    # 3. The in-memory Lab state is gone too.
    assert USER not in _PAPER_WATCHLIST
    assert not [r for r in _RUNS.values() if r.get("user_id") == USER]
    assert not [a for a in _ANALYSES.values() if a.get("user_id") == USER]

    # 4. And the other per-user caches: the AuthStore/lock and the spend tally.
    assert (USER, auth.SOURCE) not in auth._stores
    assert (USER, auth.SOURCE) not in auth._locks
    assert USER not in get_limiter()._per_user


async def test_delete_is_atomic_a_failure_mid_delete_removes_nothing(
    client: Any,
    db_env: Any,
    clerk: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Atomicity: a failure *after* revoke but *within* the delete step

    leaves the account fully intact, never half-erased. Revoke runs first, as a
    best-effort network call outside the transaction; the erase itself is a single
    `DELETE FROM users` in one transaction, so a fault anywhere in it removes
    nothing — the reverse of the centerpiece, and the property the split
    `logout`-then-delete of two commits did not have.

    The fault is injected by making the delete statement itself blow up, which
    fails the request *before* the transaction writes anything — a clean rollback
    with no half-applied cascade and no lock left held for the next test.
    """
    await _seed_every_table(db_env)

    revoked_with: list[str] = []

    async def _fake_revoke(token: str, client_id: Any, client_secret: Any) -> bool:
        revoked_with.append(token)
        return True

    monkeypatch.setattr(auth, "revoke_token", _fake_revoke)

    # Simulate a crash in the delete step: building the DELETE raises, so the
    # request aborts after revoke but before any row is touched.
    from api.routes import account as account_route

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("simulated crash mid-delete")

    monkeypatch.setattr(account_route, "sa_delete", _boom)

    before = await _row_counts(db_env)
    assert all(n >= 1 for n in before.values()), before

    with pytest.raises(RuntimeError, match="simulated crash mid-delete"):
        await client.request("DELETE", "/account", headers=bearer(clerk, USER))

    # 1. Revocation was still attempted (it runs before the transaction).
    assert revoked_with == ["refresh-token"]

    # 2. Nothing was removed — every table is exactly as it started, never half.
    after = await _row_counts(db_env)
    assert after == before, after


async def test_a_re_used_id_gets_a_fresh_row_after_deletion(
    client: Any,
    db_env: Any,
    clerk: rsa.RSAPrivateKey,
) -> None:
    """The seen-user cache must be evicted, or a re-signed-in id gets no row.

    `ensure_user` skips the insert for an id it has already seen this process.
    If deletion did not forget the id, the next authenticated request would find
    no `users` row and never recreate it, and the user's first per-user write
    would fail an FK. This pins the eviction.
    """
    await _seed_every_table(db_env)
    await client.request("DELETE", "/account", headers=bearer(clerk, USER))
    assert USER not in deps._SEEN_USERS

    # A later authenticated call recreates the row (via register_identity).
    status = await client.get("/auth/status", headers=bearer(clerk, USER))
    assert status.status_code == 200
    async with db_env() as session:
        rows = (await session.execute(select(User.id).where(User.id == USER))).scalars().all()
    assert rows == [USER]


async def test_delete_account_requires_a_token(client: Any) -> None:
    """No JWT, no deletion — a user can only delete their own data."""
    assert (await client.request("DELETE", "/account")).status_code == 401
