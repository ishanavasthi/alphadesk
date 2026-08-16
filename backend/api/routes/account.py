"""`DELETE /account` — the DPDP "delete my data" surface (card L1).

The moment someone else's net worth is in the database, AlphaDesk is a data
fiduciary under the DPDP Act, and the right to erasure is not optional. This
route is that right, implemented as a **single, ordered, total** operation:

1. **Revoke upstream first — outside the DB transaction.** `revoke_only(user_id)`
   calls the broker's RFC 7009 revocation endpoint for the refresh token and
   *nothing else* — it does **not** delete the `broker_links` row (unlike
   `logout`). Deleting our copy without revoking would leave a live grant on IND
   Money's side the user can neither see nor reach — "we forgot your token" is
   not "your access is gone". This is a best-effort network call: an upstream
   failure still proceeds (refusing would strand the user) but is reported.

2. **Cascade-delete the user in ONE transaction.** `DELETE FROM users WHERE id =
   :uid` removes the row every other table hangs off, and `broker_links`,
   `oauth_pending`, `snapshot_days` and `watchlist` are declared `ON DELETE
   CASCADE` at the FK level (V2_PLAN §6; `db.models`), with `snapshot_holdings` /
   `snapshot_raw` cascading behind `snapshot_days`. This is a schema guarantee,
   not an ORM convention: one `DELETE`, one `commit`, wipes the user's entire
   footprint inside Postgres — **including** the `broker_links` row, which is why
   step 1 must not delete it separately. A crash anywhere in this transaction
   rolls the whole thing back, so the account is always either wholly present or
   wholly gone, never the half-deleted state a second, earlier commit would open.
   `test_account_deletion.py` proves zero rows survive in *every* table, and that
   a failure mid-delete leaves nothing removed.

3. **Purge the process caches.** The DB cascade cannot reach what lives in
   memory: the Lab's per-user run/analysis registry and the no-database
   watchlist fallback (`api.main.purge_user_lab_state`), the cached portfolio
   connector (`evict_connector`), the cached `AuthStore` and its lock — which
   hold decrypted tokens — (`forget_auth_store`), the "already seen this user"
   write-avoidance set, the overview spend tally, and the adoption caches. All
   are keyed by `user_id`, so a complete deletion has to clear them too — and
   clearing the seen-user set is load-bearing: a re-used Clerk id signing in
   again must get a fresh `users` row, or its first per-user write fails an FK
   onto a row that no longer exists.

**JWT-only.** A user deletes *their own* data; the id comes from a verified
Clerk session (`CurrentUser`), never a parameter. There is no admin path and no
"delete user X" — the F3 §5 interim admin surface was removed in this same card.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from agents.portfolio.spend import get_limiter
from api.deps import CurrentUser, forget_seen_user
from db.models import User
from db.session import async_session
from tools.ind_money_auth import forget_auth_store, revoke_only

_log = logging.getLogger(__name__)

router = APIRouter(tags=["account"])


@router.delete("/account")
async def delete_account(
    user_id: CurrentUser,
    session: AsyncSession = Depends(async_session),
) -> dict[str, Any]:
    """Erase the caller: revoke upstream, cascade-delete every row, confirm.

    Returns the revocation outcome alongside the confirmation so the UI can tell
    the user whether their broker grant was also killed at the source.
    """
    # 1. Revoke the broker grant upstream FIRST, as a best-effort network call
    #    OUTSIDE the delete transaction. This does not touch any DB row of ours —
    #    the broker_links row goes with the cascade below, in one transaction, so
    #    there is never a window where the link is gone but the account is not.
    revocation = await revoke_only(user_id)

    # 2. One transaction, one commit: DELETE FROM users cascades every dependent
    #    row (schema-level ON DELETE CASCADE, V2_PLAN §6) — broker_links, the
    #    entire snapshot history, oauth_pending and the paper watchlist. Atomic by
    #    construction: a crash here rolls it all back, so the account is wholly
    #    present or wholly gone, never half-deleted.
    await session.execute(sa_delete(User).where(User.id == user_id))
    await session.commit()

    # 3. Nothing the user generated may survive in the process either.
    from api.main import purge_user_lab_state
    from api.routes.portfolio import evict_connector
    from services.adoption import forget_user

    purge_user_lab_state(user_id)
    evict_connector(user_id)
    forget_auth_store(user_id)
    forget_seen_user(user_id)
    get_limiter().forget_user(user_id)
    await forget_user(user_id)

    _log.info("account deleted (revoked_upstream=%s)", revocation.get("revoked_upstream"))
    return {
        "deleted": True,
        "user_id": user_id,
        "revoked_upstream": revocation.get("revoked_upstream"),
        "revocation_error": revocation.get("revocation_error"),
    }


__all__ = ["router"]
