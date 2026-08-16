"""Adoption of the pre-F3 `"local"` data by the operator (card F3).

The thing being protected is card S1's snapshot history: the IND Money MCP is
point-in-time, so a day that is lost is lost permanently, and every day captured
before identity existed is keyed on `user_id="local"`. The thing being prevented
is the obvious cheap implementation — "give it to the first user who signs in" —
which on a public deployment hands one stranger the operator's net worth.

So the wrong-email cases here are not edge cases; they are the point. The
sharpest one is `test_a_matching_claim_is_not_enough`: the token's `email` claim
is whatever an instance's JWT template emits, which can be an address its owner
typed and never verified — so a claim that *matches* the operator must still
lose to Clerk's answer about the verified primary address.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

import httpx
import pytest
from sqlalchemy import select, text

from db.models import BrokerLink, SnapshotDay, SnapshotHolding, User, Watchlist, utcnow
from services import adoption

# `asyncio_mode = auto` (pytest.ini) runs the async tests below; the sync ones
# are pure-function checks that need no loop.

OPERATOR_EMAIL = "operator@example.com"
OPERATOR_ID = "user_2operatoroperatoroperato"
STRANGER_ID = "user_2strangerstrangerstrang"


@pytest.fixture(autouse=True)
def clean_adoption(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(adoption.OPERATOR_EMAIL_ENV, raising=False)
    monkeypatch.delenv(adoption.CLERK_SECRET_ENV, raising=False)
    adoption.reset_adoption_cache()
    yield
    adoption.reset_adoption_cache()


class FakeClerk:
    """The Clerk Backend API's `GET /v1/users/{id}`, and nothing else.

    Stubbed at the HTTP layer rather than by replacing `clerk_lookup`, so the
    rule that actually carries the security weight — "primary, and verified" —
    is exercised by every test here instead of being mocked away.
    """

    def __init__(self) -> None:
        #: user_id -> (email, verified). Absent means Clerk 404s.
        self.users: dict[str, tuple[str, bool]] = {}
        self.status = 200
        self.fail = False
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            raise httpx.ConnectError("clerk is down")
        if self.status != 200:
            return httpx.Response(self.status, json={"errors": []})
        user_id = str(request.url).rsplit("/", 1)[-1]
        found = self.users.get(user_id)
        if found is None:
            return httpx.Response(404, json={"errors": []})
        email, verified = found
        return httpx.Response(
            200,
            json={
                "id": user_id,
                "primary_email_address_id": "idn_primary",
                "email_addresses": [
                    {
                        "id": "idn_primary",
                        "email_address": email,
                        "verification": {
                            "status": "verified" if verified else "unverified"
                        },
                    }
                ],
            },
        )


@pytest.fixture
def clerk_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClerk]:
    fake = FakeClerk()
    fake.users[OPERATOR_ID] = (OPERATOR_EMAIL, True)
    fake.users[STRANGER_ID] = ("someone@else.com", True)
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setenv(adoption.CLERK_SECRET_ENV, "sk_test_not_a_real_key")
    yield fake


async def _seed_local(maker: Any) -> int:
    """One `local` broker link and one `local` snapshot day with a holding."""
    async with maker() as session:
        session.add(User(id=adoption.LOCAL_USER_ID, created_at=utcnow()))
        await session.commit()
        session.add(
            BrokerLink(
                user_id=adoption.LOCAL_USER_ID,
                source="ind_money",
                access_token_enc=None,
                status="active",
            )
        )
        day = SnapshotDay(
            user_id=adoption.LOCAL_USER_ID,
            captured_on=date(2026, 8, 1),
            total_value=Decimal("1234.00"),
            captured_at=datetime(2026, 8, 1, 18, 30, tzinfo=timezone.utc),
        )
        session.add(day)
        await session.commit()
        session.add(
            SnapshotHolding(
                snapshot_id=day.id,
                source="ind_money",
                external_id="MF:1",
                asset_type="MF",
                current_value=Decimal("1234.00"),
            )
        )
        await session.commit()
        return int(day.id or 0)


async def _users(maker: Any, *ids: str) -> None:
    async with maker() as session:
        for user_id in ids:
            session.add(User(id=user_id, created_at=utcnow()))
        await session.commit()


async def _owner_of_days(maker: Any) -> list[str]:
    async with maker() as session:
        return list((await session.execute(select(SnapshotDay.user_id))).scalars().all())


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #
async def test_the_operator_adopts_the_local_history(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    snapshot_id = await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    async with db_env() as session:
        moved = await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL)

    assert moved == {"broker_links": 1, "snapshot_days": 1, "watchlist": 0}
    assert await _owner_of_days(db_env) == [OPERATOR_ID]

    async with db_env() as session:
        # The children ride along on `snapshot_id`; nothing needed to touch them.
        holdings = (
            await session.execute(
                select(SnapshotHolding).where(SnapshotHolding.snapshot_id == snapshot_id)
            )
        ).scalars().all()
        assert len(holdings) == 1
        link_owner = (await session.execute(select(BrokerLink.user_id))).scalars().one()
    assert link_owner == OPERATOR_ID


async def test_adoption_is_idempotent(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    async with db_env() as session:
        first = await adoption.adopt_local_data(session, OPERATOR_ID)
        second = await adoption.adopt_local_data(session, OPERATOR_ID)

    assert first == {"broker_links": 1, "snapshot_days": 1, "watchlist": 0}
    assert second == {"broker_links": 0, "snapshot_days": 0, "watchlist": 0}
    assert await _owner_of_days(db_env) == [OPERATOR_ID]


async def test_a_different_email_never_adopts(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure this whole module exists to prevent."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, STRANGER_ID)

    async with db_env() as session:
        moved = await adoption.maybe_adopt(session, STRANGER_ID, "someone@else.com")

    assert moved is None
    assert await _owner_of_days(db_env) == [adoption.LOCAL_USER_ID]


async def test_no_clerk_secret_never_adopts(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `CLERK_SECRET_KEY` means nobody can be identified, so nothing moves.

    Not knowing is a recoverable state (set the key, sign in again); adopting on
    a guess is not."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    async with db_env() as session:
        assert await adoption.maybe_adopt(session, OPERATOR_ID, None) is None
    assert await _owner_of_days(db_env) == [adoption.LOCAL_USER_ID]


async def test_adoption_is_off_when_the_env_var_is_unset(
    db_env: Any
) -> None:
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    async with db_env() as session:
        assert await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL) is None
    assert await _owner_of_days(db_env) == [adoption.LOCAL_USER_ID]


async def test_email_match_ignores_case_and_whitespace(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, f"  {OPERATOR_EMAIL.upper()} ")
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    async with db_env() as session:
        assert await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL)


async def test_the_signed_in_users_own_rows_are_never_overwritten(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A collision leaves the legacy row behind rather than clobbering a real one."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)
    async with db_env() as session:
        session.add(
            SnapshotDay(
                user_id=OPERATOR_ID,
                captured_on=date(2026, 8, 1),
                total_value=Decimal("9999.00"),
                captured_at=utcnow(),
            )
        )
        session.add(BrokerLink(user_id=OPERATOR_ID, source="ind_money", status="active"))
        await session.commit()

    async with db_env() as session:
        moved = await adoption.adopt_local_data(session, OPERATOR_ID)

    assert moved == {"broker_links": 0, "snapshot_days": 0, "watchlist": 0}
    async with db_env() as session:
        kept = (
            await session.execute(
                text(
                    "SELECT total_value FROM snapshot_days WHERE user_id = :u "
                    "AND captured_on = '2026-08-01'"
                ),
                {"u": OPERATOR_ID},
            )
        ).scalar_one()
    assert Decimal(kept) == Decimal("9999.00")


async def test_a_matching_claim_is_not_enough(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The hole this fix closes.**

    A JWT template can be configured to put an address in the token that its
    owner typed and never verified, and any user can add an unverified secondary
    address to their own account. If a matching *claim* were sufficient, that
    would be a self-service takeover of the operator's links and snapshots — and
    of `operator_user_id`, which is also the ambient and interim-admin identity.
    Clerk's answer about the verified primary address is what decides.
    """
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, STRANGER_ID)
    clerk_api.users[STRANGER_ID] = ("someone@else.com", True)

    async with db_env() as session:
        moved = await adoption.maybe_adopt(session, STRANGER_ID, OPERATOR_EMAIL)

    assert moved is None
    assert await _owner_of_days(db_env) == [adoption.LOCAL_USER_ID]
    assert clerk_api.calls == 1, "a matching claim must still be confirmed"


async def test_an_unverified_primary_address_never_adopts(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, STRANGER_ID)
    clerk_api.users[STRANGER_ID] = (OPERATOR_EMAIL, False)

    async with db_env() as session:
        assert await adoption.maybe_adopt(session, STRANGER_ID, OPERATOR_EMAIL) is None
    assert await _owner_of_days(db_env) == [adoption.LOCAL_USER_ID]


async def test_a_mismatched_claim_short_circuits_without_calling_clerk(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim's one legitimate job: a free *negative*."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, STRANGER_ID)

    async with db_env() as session:
        assert await adoption.maybe_adopt(session, STRANGER_ID, "no@thanks.com") is None
    assert clerk_api.calls == 0


async def test_a_clerk_outage_is_retried_not_remembered(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad minute must not cost the operator their history for good.

    The negative cache exists so a non-operator does not trigger a Clerk lookup
    on every request. Caching a *failure to reach Clerk* in it would mean a
    transient blip during the operator's very first sign-in permanently prevents
    adoption for the life of the process — and the process is a Space that can
    stay up for weeks.
    """
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    clerk_api.fail = True
    async with db_env() as session:
        assert await adoption.maybe_adopt(session, OPERATOR_ID, None) is None
    assert await _owner_of_days(db_env) == [adoption.LOCAL_USER_ID]

    clerk_api.fail = False
    async with db_env() as session:
        moved = await adoption.maybe_adopt(session, OPERATOR_ID, None)
    assert moved == {"broker_links": 1, "snapshot_days": 1, "watchlist": 0}


async def test_a_clerk_5xx_is_also_retried(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    clerk_api.status = 503
    async with db_env() as session:
        assert await adoption.maybe_adopt(session, OPERATOR_ID, None) is None

    clerk_api.status = 200
    async with db_env() as session:
        assert await adoption.maybe_adopt(session, OPERATOR_ID, None)


async def test_a_missing_secret_key_is_also_retried(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting the key without restarting the process must start working."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    monkeypatch.delenv(adoption.CLERK_SECRET_ENV, raising=False)
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    async with db_env() as session:
        assert await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL) is None

    monkeypatch.setenv(adoption.CLERK_SECRET_ENV, "sk_test_not_a_real_key")
    async with db_env() as session:
        assert await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL)


async def test_a_settled_no_is_remembered(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: a non-operator must not cost a Clerk call per request."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, STRANGER_ID)

    async with db_env() as session:
        for _ in range(3):
            assert await adoption.maybe_adopt(session, STRANGER_ID, None) is None
    assert clerk_api.calls == 1


# --------------------------------------------------------------------------- #
# Who is the operator?
# --------------------------------------------------------------------------- #
async def test_operator_user_id_is_none_without_the_env_var(db_env: Any) -> None:
    await _users(db_env, OPERATOR_ID)
    assert await adoption.operator_user_id() is None


async def test_operator_user_id_follows_the_operator_after_sign_in(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before sign-in the pre-F3 data is under `local`; after adoption it is
    under the Clerk id — and `operator_user_id` (the ambient identity for the
    legacy research pipeline) has to follow it."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    assert await adoption.operator_user_id() is None

    adoption.reset_adoption_cache()
    async with db_env() as session:
        await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL)

    adoption.reset_adoption_cache()
    assert await adoption.operator_user_id() == OPERATOR_ID


async def test_a_stranger_never_becomes_the_operator(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _users(db_env, STRANGER_ID)
    async with db_env() as session:
        await session.execute(
            text("UPDATE users SET email = :e WHERE id = :u"),
            {"e": "someone@else.com", "u": STRANGER_ID},
        )
        await session.commit()

    assert await adoption.operator_user_id() is None


async def test_an_underscore_in_the_operator_email_is_not_a_wildcard(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ILIKE` treats `_` and `%` as wildcards, and `_` is legal in an email.

    With `ilike`, an operator address of `ops_admin@example.com` also matches a
    signed-up `opsXadmin@example.com` — and whoever owns that address becomes
    `operator_user_id()`, which is the ambient identity for the legacy research
    pipeline.
    """
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, "ops_admin@example.com")
    await _users(db_env, STRANGER_ID)
    async with db_env() as session:
        await session.execute(
            text("UPDATE users SET email = :e WHERE id = :u"),
            {"e": "opsXadmin@example.com", "u": STRANGER_ID},
        )
        await session.commit()

    assert await adoption.operator_user_id() is None


async def test_a_percent_in_the_operator_email_is_not_a_wildcard(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, "%@example.com")
    await _users(db_env, STRANGER_ID)
    async with db_env() as session:
        await session.execute(
            text("UPDATE users SET email = :e WHERE id = :u"),
            {"e": "anybody@example.com", "u": STRANGER_ID},
        )
        await session.commit()

    assert await adoption.operator_user_id() is None


# --------------------------------------------------------------------------- #
# Which Clerk address counts (pure, no Clerk instance needed)
# --------------------------------------------------------------------------- #
def test_only_a_verified_primary_address_counts() -> None:
    payload = {
        "primary_email_address_id": "idn_1",
        "email_addresses": [
            {
                "id": "idn_1",
                "email_address": "operator@example.com",
                "verification": {"status": "verified"},
            }
        ],
    }
    assert adoption._primary_verified_email(payload) == "operator@example.com"


def test_an_unverified_primary_address_does_not_count() -> None:
    payload = {
        "primary_email_address_id": "idn_1",
        "email_addresses": [
            {
                "id": "idn_1",
                "email_address": "operator@example.com",
                "verification": {"status": "unverified"},
            }
        ],
    }
    assert adoption._primary_verified_email(payload) is None


def test_a_secondary_address_is_not_mistaken_for_the_primary() -> None:
    """Anyone can add an unverified secondary address to their own account. If
    a secondary counted, adoption would be a self-service takeover."""
    payload = {
        "primary_email_address_id": "idn_1",
        "email_addresses": [
            {
                "id": "idn_2",
                "email_address": "operator@example.com",
                "verification": {"status": "verified"},
            },
            {
                "id": "idn_1",
                "email_address": "stranger@example.com",
                "verification": {"status": "verified"},
            },
        ],
    }
    assert adoption._primary_verified_email(payload) == "stranger@example.com"


def test_a_junk_payload_yields_no_email() -> None:
    assert adoption._primary_verified_email(None) is None
    assert adoption._primary_verified_email({}) is None
    assert adoption._primary_verified_email({"email_addresses": "nope"}) is None


async def test_clerk_lookup_is_skipped_without_a_secret_key() -> None:
    assert await adoption.clerk_primary_email("user_whatever") is None


async def test_adoption_also_rekeys_a_local_watchlist_row(
    db_env: Any, clerk_api: FakeClerk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `local` watchlist row (F4 schema) adopts too — symmetry with links/days."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _users(db_env, OPERATOR_ID)
    async with db_env() as session:
        session.add(User(id=adoption.LOCAL_USER_ID, created_at=utcnow()))
        await session.commit()
        session.add(
            Watchlist(user_id=adoption.LOCAL_USER_ID, symbol="DEMOX", company="Demo X")
        )
        await session.commit()

    async with db_env() as session:
        moved = await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL)

    assert moved["watchlist"] == 1
    async with db_env() as session:
        owners = (await session.execute(select(Watchlist.user_id))).scalars().all()
    assert owners == [OPERATOR_ID]
