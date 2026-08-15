"""Adoption of the pre-F3 `"local"` data by the operator (card F3).

The thing being protected is card S1's snapshot history: the IND Money MCP is
point-in-time, so a day that is lost is lost permanently, and every day captured
before identity existed is keyed on `user_id="local"`. The thing being prevented
is the obvious cheap implementation — "give it to the first user who signs in" —
which on a public deployment hands one stranger the operator's net worth.

So the wrong-email cases here are not edge cases; they are the point.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

import pytest
from sqlalchemy import select, text

from db.models import BrokerLink, SnapshotDay, SnapshotHolding, User, utcnow
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
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    snapshot_id = await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    async with db_env() as session:
        moved = await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL)

    assert moved == {"broker_links": 1, "snapshot_days": 1}
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

    assert first == {"broker_links": 1, "snapshot_days": 1}
    assert second == {"broker_links": 0, "snapshot_days": 0}
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


async def test_no_email_never_adopts(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session token with no email claim and no Clerk secret cannot identify
    anybody, so nothing moves. Not knowing is a recoverable state; adopting on a
    guess is not."""
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
    db_env: Any, monkeypatch: pytest.MonkeyPatch
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

    assert moved == {"broker_links": 0, "snapshot_days": 0}
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


# --------------------------------------------------------------------------- #
# Who is the operator?
# --------------------------------------------------------------------------- #
async def test_operator_user_id_is_none_without_the_env_var(db_env: Any) -> None:
    await _users(db_env, OPERATOR_ID)
    assert await adoption.operator_user_id() is None
    assert await adoption.admin_identity() == adoption.LOCAL_USER_ID


async def test_admin_identity_follows_the_operator_after_sign_in(
    db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before sign-in the pre-F3 data is under `local`; after adoption it is
    under the Clerk id — and the interim admin path has to follow it, or the
    operator's dashboard goes blank on the day they first sign in."""
    monkeypatch.setenv(adoption.OPERATOR_EMAIL_ENV, OPERATOR_EMAIL)
    await _seed_local(db_env)
    await _users(db_env, OPERATOR_ID)

    assert await adoption.admin_identity() == adoption.LOCAL_USER_ID

    adoption.reset_adoption_cache()
    async with db_env() as session:
        await adoption.maybe_adopt(session, OPERATOR_ID, OPERATOR_EMAIL)

    adoption.reset_adoption_cache()
    assert await adoption.operator_user_id() == OPERATOR_ID
    assert await adoption.admin_identity() == OPERATOR_ID


async def test_a_stranger_never_becomes_the_admin_identity(
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
    assert await adoption.admin_identity() == adoption.LOCAL_USER_ID


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
