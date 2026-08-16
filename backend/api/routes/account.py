"""`DELETE /account` — the DPDP "delete my data" surface (card L1).

The moment someone else's net worth is in the database, AlphaDesk is a data
fiduciary under the DPDP Act, and the right to erasure is not optional. This
route is that right, implemented as a **single, ordered, total** operation:

1. **Revoke upstream first.** `logout(user_id)` calls the broker's RFC 7009
   revocation endpoint for the refresh token and *then* deletes the local
   `broker_links` row (F3's `AuthStore.logout`). Deleting our copy without
   revoking would leave a live grant on IND Money's side the user can neither
   see nor reach — "we forgot your token" is not "your access is gone". An
   upstream failure still proceeds (refusing would strand the user) but is
   reported.

2. **Cascade-delete the user.** `DELETE FROM users WHERE id = :uid` removes the
   row every other table hangs off. `broker_links`, `oauth_pending`,
   `snapshot_days` and `watchlist` are declared `ON DELETE CASCADE` at the FK
   level (V2_PLAN §6; `db.models`), and `snapshot_holdings` / `snapshot_raw`
   cascade with `snapshot_days`. This is a schema guarantee, not an ORM
   convention: one `DELETE` wipes the user's entire footprint inside Postgres.
   `test_account_deletion.py` proves zero rows survive in *every* table.

3. **Purge the process caches.** The DB cascade cannot reach what lives in
   memory: the Lab's per-user run/analysis registry and the no-database
   watchlist fallback (`api.main.purge_user_lab_state`), the cached connector
   and its `AuthStore` (which holds decrypted tokens), the "already seen this
   user" write-avoidance set, and the adoption caches. All are keyed by
   `user_id`, so a complete deletion has to clear them too — and clearing the
   seen-user set is load-bearing: a re-used Clerk id signing in again must get a
   fresh `users` row, or its first per-user write fails an FK onto a row that no
   longer exists.

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

from api.deps import CurrentUser, forget_seen_user
from db.models import User
from db.session import async_session
from tools.ind_money_auth import logout

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
    # 1. Revoke the broker token upstream, then drop the local link row (F3).
    unlink = await logout(user_id)

    # 2. Cascade-delete the user. Every dependent row goes with it (schema-level
    #    ON DELETE CASCADE, V2_PLAN §6) — including the entire snapshot history
    #    and the paper watchlist.
    await session.execute(sa_delete(User).where(User.id == user_id))
    await session.commit()

    # 3. Nothing the user generated may survive in the process either.
    from api.main import purge_user_lab_state
    from api.routes.portfolio import evict_connector
    from services.adoption import forget_user

    purge_user_lab_state(user_id)
    evict_connector(user_id)
    forget_seen_user(user_id)
    await forget_user(user_id)

    _log.info("account deleted (revoked_upstream=%s)", unlink.get("revoked_upstream"))
    return {
        "deleted": True,
        "user_id": user_id,
        "revoked_upstream": unlink.get("revoked_upstream"),
        "revocation_error": unlink.get("revocation_error"),
    }


__all__ = ["router"]
