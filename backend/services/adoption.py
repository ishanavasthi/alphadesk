"""One-off adoption of the pre-F3 ``"local"`` data by its real owner (card F3).

Everything AlphaDesk stored before per-user identity existed is keyed on the
constant ``user_id="local"``: the operator's IND Money link, and — the part that
cannot be recreated — every daily net-worth snapshot card S1 has captured since
it shipped. The source is point-in-time, so a lost snapshot day is lost
permanently. This module exists so that turning identity on does not orphan that
history behind an id nobody can sign in as.

## The rule

Adoption runs **only** for the person named in ``ALPHADESK_OPERATOR_EMAIL``, and
only against their *verified primary* email address. It is deliberately not
"the first user to sign in": a first-comer rule on a public deployment hands one
stranger the operator's entire portfolio history, and the whole reason F3 exists
is that the previous design let exactly that class of mistake happen. With the
variable unset, adoption never runs at all.

## Where the email comes from

A default Clerk session token carries **no** email claim (F2 §1), so the claim
is checked first and the Clerk Backend API is the fallback — which needs
``CLERK_SECRET_KEY``. Without either, adoption cannot establish who is signing
in and therefore does not run. That is the correct failure direction: no
adoption is a recoverable state (set the key, sign in again), a wrong adoption
is not.

Whatever email is resolved is written back onto the ``users`` row, which is what
later lets :func:`operator_user_id` answer "which Clerk id is the operator?"
without another round-trip to Clerk.

## Idempotent by construction

Adoption moves rows *off* ``"local"``. Run it twice and the second pass finds
nothing to move. Rows that would collide with something the target user already
has (same broker source, same captured day) are left behind rather than
overwritten — the signed-in user's own data always wins.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BrokerLink, SnapshotDay, User

log = logging.getLogger(__name__)

#: The identity every pre-F3 row is keyed on.
LOCAL_USER_ID = "local"

OPERATOR_EMAIL_ENV = "ALPHADESK_OPERATOR_EMAIL"
CLERK_SECRET_ENV = "CLERK_SECRET_KEY"
CLERK_API_BASE = "https://api.clerk.com/v1"

#: Clerk ids this process has already run adoption for. Purely a
#: work-avoidance cache — the SQL underneath is idempotent, so losing it on
#: restart costs two no-op UPDATEs, never correctness.
_adopted: set[str] = set()

#: Resolved operator Clerk id, cached per process. ``False`` means "looked and
#: found nobody", which is distinct from ``None`` ("not looked yet").
_operator_id: Optional[str] | bool = None


def reset_adoption_cache() -> None:
    """Forget which users have been adopted and who the operator is. For tests."""
    global _operator_id
    _adopted.clear()
    _operator_id = None


def operator_email() -> Optional[str]:
    """The operator's email, or None when adoption is switched off."""
    value = (os.environ.get(OPERATOR_EMAIL_ENV) or "").strip().lower()
    return value or None


def _same_email(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b and a.strip().lower() == b.strip().lower())


# --------------------------------------------------------------------------- #
# Resolving the signed-in user's verified primary email
# --------------------------------------------------------------------------- #
async def clerk_primary_email(user_id: str) -> Optional[str]:
    """The user's **verified primary** email from the Clerk Backend API.

    Returns None when ``CLERK_SECRET_KEY`` is unset, when Clerk cannot be
    reached, or when the primary address is not verified. Every one of those is
    "we do not know who this is", and this function's only caller treats not
    knowing as "do not adopt".
    """
    secret = (os.environ.get(CLERK_SECRET_ENV) or "").strip()
    if not secret:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{CLERK_API_BASE}/users/{user_id}",
                headers={"Authorization": f"Bearer {secret}"},
            )
    except Exception:  # noqa: BLE001 - Clerk being unreachable is not our caller's problem
        log.warning("adoption: could not reach the Clerk Backend API")
        return None
    if resp.status_code != 200:
        log.warning("adoption: Clerk user lookup returned %s", resp.status_code)
        return None
    return _primary_verified_email(resp.json())


def _primary_verified_email(payload: Any) -> Optional[str]:
    """Pick the primary address out of a Clerk user object, if it is verified.

    Split out from the HTTP call so the "which address counts" rule is testable
    without a Clerk instance — and it is the rule that carries the security
    weight here, not the request.
    """
    if not isinstance(payload, dict):
        return None
    primary_id = payload.get("primary_email_address_id")
    addresses = payload.get("email_addresses")
    if not isinstance(addresses, list):
        return None
    for entry in addresses:
        if not isinstance(entry, dict):
            continue
        if primary_id is not None and entry.get("id") != primary_id:
            continue
        verification = entry.get("verification")
        status = verification.get("status") if isinstance(verification, dict) else None
        if status != "verified":
            return None
        address = entry.get("email_address")
        return address.strip() if isinstance(address, str) and address.strip() else None
    return None


async def resolve_email(user_id: str, claim_email: Optional[str]) -> Optional[str]:
    """The signed-in user's email: the token's claim, else Clerk's own answer."""
    if claim_email:
        return claim_email
    return await clerk_primary_email(user_id)


# --------------------------------------------------------------------------- #
# The adoption itself
# --------------------------------------------------------------------------- #
async def adopt_local_data(session: AsyncSession, user_id: str) -> dict[str, int]:
    """Move every ``"local"`` row onto ``user_id``. Returns what moved.

    Two statements, each with a NOT-EXISTS guard so a collision leaves the
    legacy row where it is instead of failing the whole adoption on a unique
    constraint. ``snapshot_holdings`` and ``snapshot_raw`` hang off
    ``snapshot_days.id`` and move with their parent without being touched.
    """
    if user_id == LOCAL_USER_ID:
        return {"broker_links": 0, "snapshot_days": 0}

    taken_sources = select(BrokerLink.source).where(BrokerLink.user_id == user_id)
    links = await session.execute(
        update(BrokerLink)
        .where(
            BrokerLink.user_id == LOCAL_USER_ID,
            BrokerLink.source.not_in(taken_sources),
        )
        .values(user_id=user_id)
    )

    taken_days = select(SnapshotDay.captured_on).where(SnapshotDay.user_id == user_id)
    days = await session.execute(
        update(SnapshotDay)
        .where(
            SnapshotDay.user_id == LOCAL_USER_ID,
            SnapshotDay.captured_on.not_in(taken_days),
        )
        .values(user_id=user_id)
    )

    await session.commit()
    return {
        "broker_links": int(links.rowcount or 0),
        "snapshot_days": int(days.rowcount or 0),
    }


async def maybe_adopt(
    session: AsyncSession, user_id: str, claim_email: Optional[str]
) -> Optional[dict[str, int]]:
    """Adopt the ``"local"`` data for ``user_id`` **iff** they are the operator.

    Called once per process per user from `api.deps.current_user`. Returns None
    when adoption is off, when this is not the operator, or when the user's
    email could not be established — all of which are ordinary, silent outcomes
    for every user who is not the one person named in the environment.
    """
    wanted = operator_email()
    if not wanted or user_id in _adopted:
        return None

    email = await resolve_email(user_id, claim_email)
    if not _same_email(email, wanted):
        # Deliberately marked as handled: a non-operator must not cause a Clerk
        # API lookup on every single request either.
        _adopted.add(user_id)
        return None

    await _record_email(session, user_id, email)
    moved = await adopt_local_data(session, user_id)
    _adopted.add(user_id)
    global _operator_id
    _operator_id = user_id
    log.info(
        "adoption: %s adopted pre-F3 data (broker_links=%d snapshot_days=%d)",
        user_id,
        moved["broker_links"],
        moved["snapshot_days"],
    )
    return moved


async def _record_email(session: AsyncSession, user_id: str, email: Optional[str]) -> None:
    """Store the resolved email on the `users` row so it can be found later."""
    if not email:
        return
    await session.execute(
        update(User).where(User.id == user_id).values(email=email)
    )
    await session.commit()


# --------------------------------------------------------------------------- #
# Who is the operator?
# --------------------------------------------------------------------------- #
async def operator_user_id() -> Optional[str]:
    """The Clerk id of the operator, or None.

    Answered from the ``users`` row whose email matches
    ``ALPHADESK_OPERATOR_EMAIL`` — which only exists once that person has signed
    in at least once, because that is when the email is recorded. Used by two
    callers that need an identity but do not have a token: the legacy research
    pipeline (`tools.ind_money_auth.ambient_user_id`) and the interim
    admin-header path on ``/portfolio/*``.

    **Never falls back to "the only user".** An empty answer is an answer.
    """
    global _operator_id
    if _operator_id is not None:
        return _operator_id or None

    wanted = operator_email()
    if not wanted:
        _operator_id = False
        return None

    from tools.ind_money_auth import _session  # local: avoids an import cycle

    async with _session() as session:
        if session is None:
            return None
        result = await session.execute(
            select(User.id).where(User.email.ilike(wanted)).order_by(User.created_at)
        )
        found = result.scalars().first()
    _operator_id = found or False
    return found


async def admin_identity() -> str:
    """Which user an interim C0 admin-header request acts as.

    **Interim — delete with the admin path at card L1.** Until
    ``NEXT_PUBLIC_AUTH_ENABLED`` is flipped there is no sign-in UI in
    production, so the operator's only way into their own dashboard is the C0
    admin secret. It maps to the operator's Clerk id once they have signed in
    (post-adoption, that is where the data lives) and otherwise to ``"local"``
    (pre-adoption, that is where the data lives). It is never a stranger, and it
    is never "whichever user exists".
    """
    return await operator_user_id() or LOCAL_USER_ID


__all__ = [
    "CLERK_SECRET_ENV",
    "LOCAL_USER_ID",
    "OPERATOR_EMAIL_ENV",
    "admin_identity",
    "adopt_local_data",
    "clerk_primary_email",
    "maybe_adopt",
    "operator_email",
    "operator_user_id",
    "reset_adoption_cache",
    "resolve_email",
]
