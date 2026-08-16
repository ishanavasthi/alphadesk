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

**Only from the Clerk Backend API, and only if it is the verified primary
address.** The token's `email` claim is used for exactly one thing: a cheap
*negative* pre-filter. A claim that does not match the operator's address ends
the check without a network call; a claim that *does* match proves nothing and
still has to be confirmed.

That asymmetry is the whole security property. `deps.claim_email` reads whatever
`email`-ish claim an instance's JWT template happens to put in the token, and a
JWT template can be configured to emit an address the user typed and never
verified. Trusting it would mean anyone who can add `operator@example.com` as an
unverified secondary address to their own account inherits the operator's links
and snapshots — and becomes :func:`operator_user_id`, which is the ambient and
interim-admin identity as well. So the confirmation goes to Clerk, which is the
only party that knows which address is primary and which is verified.

The consequence is that adoption needs ``CLERK_SECRET_KEY``. Without it,
adoption never runs — the correct failure direction: no adoption is a
recoverable state (set the key, sign in again), a wrong adoption is not.

The **verified** email is written back onto the ``users`` row, which is what
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
from typing import Any, Final, Optional

import httpx
from sqlalchemy import func, select, update
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
#: Why a lookup produced no email. The distinction is not cosmetic: a
#: *deterministic* "no" may be remembered for the process (see `_adopted`),
#: while a *transient* one must be retried — otherwise one Clerk blip during
#: the operator's first sign-in permanently prevents adoption.
OK: Final = "ok"
UNCONFIGURED: Final = "unconfigured"  # no CLERK_SECRET_KEY; free to retry
UNAVAILABLE: Final = "unavailable"  # network / non-200; transient
REFUSED: Final = "refused"  # Clerk answered, and the answer is no


async def clerk_lookup(user_id: str) -> tuple[Optional[str], str]:
    """`(verified primary email, outcome)` from the Clerk Backend API.

    The outcome is what the caller needs and a bare `None` cannot express:
    "Clerk says this user's primary address is unverified" is a permanent no,
    while "Clerk timed out" is a maybe, and remembering the second one as if it
    were the first is how a transient blip turns into permanent data loss.
    """
    secret = (os.environ.get(CLERK_SECRET_ENV) or "").strip()
    if not secret:
        return None, UNCONFIGURED
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{CLERK_API_BASE}/users/{user_id}",
                headers={"Authorization": f"Bearer {secret}"},
            )
    except Exception:  # noqa: BLE001 - Clerk being unreachable is not our caller's problem
        log.warning("adoption: could not reach the Clerk Backend API")
        return None, UNAVAILABLE
    if resp.status_code != 200:
        log.warning("adoption: Clerk user lookup returned %s", resp.status_code)
        # A 5xx or a rate limit is transient; a 4xx is Clerk telling us no.
        return None, REFUSED if 400 <= resp.status_code < 500 else UNAVAILABLE
    email = _primary_verified_email(resp.json())
    return (email, OK) if email else (None, REFUSED)


async def clerk_primary_email(user_id: str) -> Optional[str]:
    """The user's verified primary email, or None. See :func:`clerk_lookup`."""
    return (await clerk_lookup(user_id))[0]


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


async def resolve_operator_email(
    user_id: str, claim_email: Optional[str], wanted: str
) -> tuple[Optional[str], str]:
    """Is this user the operator? `(verified email, outcome)`.

    The token claim is a **negative pre-filter only**: a claim that disagrees
    with `wanted` ends the check for free, and a claim that agrees is treated as
    saying nothing at all. Confirmation always comes from Clerk, because a JWT
    template can be configured to emit an address its owner never verified, and
    an unverified secondary address is something any user can add to their own
    account.
    """
    if claim_email and not _same_email(claim_email, wanted):
        return None, REFUSED
    email, outcome = await clerk_lookup(user_id)
    if outcome != OK:
        return None, outcome
    return (email, OK) if _same_email(email, wanted) else (None, REFUSED)


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

    Called from `api.deps.register_identity`, so on every authenticated request
    until this user has a settled answer. Returns None when adoption is off,
    when this is not the operator, or when the answer could not be established —
    ordinary, silent outcomes for everyone who is not the one person named in
    the environment.

    **Only a settled answer is remembered.** A Clerk outage or a missing
    ``CLERK_SECRET_KEY`` leaves `_adopted` untouched, so the next request tries
    again; caching those would let one bad minute during the operator's first
    sign-in strand their entire snapshot history behind ``"local"`` for the life
    of the process.
    """
    wanted = operator_email()
    if not wanted or user_id in _adopted:
        return None

    email, outcome = await resolve_operator_email(user_id, claim_email, wanted)
    if outcome != OK:
        if outcome == REFUSED:
            # Clerk answered and the answer is "not the operator". Settled, so
            # remember it — a non-operator must not cost a Clerk lookup on every
            # single request. `UNCONFIGURED`/`UNAVAILABLE` fall through
            # uncached: neither is an answer about *this user*.
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
        # `func.lower(...) == wanted`, not `ilike(wanted)`: LIKE treats `%` and
        # `_` as wildcards, and `_` is legal in an email local part. With
        # `ilike`, an `ALPHADESK_OPERATOR_EMAIL` of `ops_admin@example.com`
        # would also match a signed-up `opsXadmin@example.com` — a stranger
        # promoted to operator by a character nobody thought was special.
        # `wanted` is already lowercased by `operator_email()`.
        result = await session.execute(
            select(User.id)
            .where(func.lower(User.email) == wanted)
            .order_by(User.created_at)
        )
        found = result.scalars().first()
    _operator_id = found or False
    return found


async def forget_user(user_id: str) -> None:
    """Drop a deleted user from the adoption caches (card L1, delete-my-data).

    `maybe_adopt` remembers a settled "not the operator" answer per user, and
    `operator_user_id` caches the resolved operator id. When an account is
    deleted, a stale "already decided" entry would make a later sign-in under a
    re-used id skip the check it should re-run. Clearing the operator id if it
    was this user also lets `operator_user_id` re-resolve from the table.
    """
    global _operator_id
    _adopted.discard(user_id)
    if _operator_id == user_id:
        _operator_id = None


__all__ = [
    "CLERK_SECRET_ENV",
    "LOCAL_USER_ID",
    "OPERATOR_EMAIL_ENV",
    "adopt_local_data",
    "forget_user",
    "OK",
    "REFUSED",
    "UNAVAILABLE",
    "UNCONFIGURED",
    "clerk_lookup",
    "clerk_primary_email",
    "maybe_adopt",
    "operator_email",
    "operator_user_id",
    "reset_adoption_cache",
    "resolve_operator_email",
]
