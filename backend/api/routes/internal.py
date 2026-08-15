"""Machine-to-machine routes: the nightly snapshot trigger and the raw prune.

These are **not** behind the C0 admin gate. Different caller, different secret,
different failure mode: `/portfolio/*` is guarded so a human cannot read the
operator's net worth, while these are guarded so a stranger cannot make the
backend spend its source rate limit. A GitHub Actions runner is not an operator,
and giving it the admin secret would hand a CI system the ability to read
holdings and disconnect the account.

**Fail-closed, always.** With `CRON_SECRET` unset the routes answer 503 — the
one thing they must never do is run because nobody configured a secret. 503
rather than 401 on purpose: an operator staring at a red workflow needs to be
able to tell "you have not configured me" from "your secret is wrong", and those
are the two mistakes that get made.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.portfolio import get_connector
from db.session import async_session
from portfolio.connectors import PortfolioConnector
from services.snapshots import (
    RAW_RETENTION_DAYS,
    capture_all,
    prune_raw,
)

log = logging.getLogger(__name__)

CRON_SECRET_ENV = "CRON_SECRET"
CRON_SECRET_HEADER = "x-cron-secret"


def _require_cron_secret(x_cron_secret: Optional[str] = Header(default=None)) -> None:
    """Guard both routes on a shared secret sent as ``x-cron-secret``.

    Compared with :func:`secrets.compare_digest` rather than ``==``: the header
    is attacker-controlled and a timing-distinguishable comparison over a
    long-lived secret is a real, if slow, oracle.
    """
    expected = os.environ.get(CRON_SECRET_ENV) or ""
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "cron_not_configured",
                "message": (
                    "This deployment has no CRON_SECRET configured, so scheduled "
                    "capture is disabled rather than open."
                ),
            },
        )
    supplied = x_cron_secret or ""
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "bad_cron_secret",
                "message": "A valid x-cron-secret header is required.",
            },
        )


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(_require_cron_secret)],
)


@router.post("/snapshot")
async def snapshot(
    session: AsyncSession = Depends(async_session),
    # The same process-wide connector the dashboard reads through, injected the
    # same way. Deliberately shared: `IndMoneyConnector` remembers a definitive
    # revocation, and a capture job that built its own instance would re-learn
    # that fact by making a doomed call every night. Declared as a dependency
    # rather than called inline so a test can substitute it the same way it does
    # for `/portfolio/*`.
    connector: PortfolioConnector = Depends(get_connector),
) -> dict[str, Any]:
    """Capture today's attributed day for every user that needs it.

    Idempotent: called twice on the same attributed day — which is exactly what
    the 23:45 IST primary and the ~01:00 IST retry do — the second call is a
    no-op that reports its users as `skipped`.

    Answers 200 with counts even when individual users failed. The workflow reads
    `errors` and the response body; a non-2xx here would mean the *request*
    failed, and conflating "three users are unlinked" with "the backend is down"
    would make the retry hammer a healthy server.
    """
    report = await capture_all(session, connector=connector)
    log.info(
        "snapshot run for %s: captured=%d skipped=%d errors=%d",
        report.captured_on,
        report.users_captured,
        report.skipped,
        report.errors,
    )
    return report.as_dict()


@router.post("/prune")
async def prune(
    days: int = Query(
        RAW_RETENTION_DAYS,
        ge=1,
        le=3650,
        description="Delete snapshot_raw rows older than this many days.",
    ),
    session: AsyncSession = Depends(async_session),
) -> dict[str, Any]:
    """Drop raw payloads past their retention window.

    Only `snapshot_raw`. The daily totals and normalized holdings are kept
    forever — they are small, they are the actual history, and unlike the raw
    payloads they can never be re-acquired.
    """
    deleted = await prune_raw(session, days=days)
    log.info("prune: deleted %d snapshot_raw rows older than %d days", deleted, days)
    return {"deleted": deleted, "days": days}


__all__ = ["CRON_SECRET_ENV", "CRON_SECRET_HEADER", "router"]
