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
from collections.abc import Callable
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.portfolio import connector_factory as connector_factory_dep
from portfolio.connectors import PortfolioConnector
from services.snapshots import (
    RAW_RETENTION_DAYS,
    capture_all,
    optional_session,
    prune_raw,
)

log = logging.getLogger(__name__)

CRON_SECRET_ENV = "CRON_SECRET"
CRON_SECRET_HEADER = "x-cron-secret"


def _require_database(session: Optional[AsyncSession]) -> AsyncSession:
    """503 rather than a 500 when the Space has a cron secret but no database.

    That combination is a real half-finished deployment — the runbook sets
    `CRON_SECRET` and `DATABASE_URL` as two separate Space secrets — and without
    this the engine raises on first use and the workflow sees an opaque 500,
    which it would dutifully retry four times against a backend that cannot
    possibly succeed.

    Shares the 503 status with `cron_not_configured` but carries a **distinct
    `code`**, which is what lets the workflow tell "this deployment is
    misconfigured, stop" from a Hugging Face edge 503 during a cold start, which
    it must keep retrying. See `.github/workflows/snapshot.yml`.
    """
    if session is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "no_database",
                "message": (
                    "This deployment has no DATABASE_URL configured, so there is "
                    "nowhere to write a snapshot."
                ),
            },
        )
    return session


def _secret_matches(supplied: str, expected: str) -> bool:
    """Constant-time compare of a header value against the configured secret.

    Compared with :func:`secrets.compare_digest` rather than ``==`` because the
    header is attacker-controlled and a timing-distinguishable comparison over a
    long-lived secret is a real, if slow, oracle.

    **Compared as bytes, not as `str`.** `compare_digest` raises `TypeError` on
    any `str` containing a character above U+007F, and Starlette decodes headers
    as latin-1 — so a single non-ASCII byte in `x-cron-secret` would have turned
    a wrong secret into an unhandled 500 instead of a 401. That is both a worse
    answer and a free liveness oracle for anyone probing the endpoint.

    The two sides are encoded differently on purpose: latin-1 recovers the exact
    bytes the client put on the wire (undoing Starlette's decode), while the
    environment value is UTF-8 as Python read it from the OS. For an ASCII
    secret — which `openssl rand -base64 32` always produces — the two are
    identical; for a non-ASCII one they still compare the real wire bytes rather
    than mojibake.
    """
    return secrets.compare_digest(
        supplied.encode("latin-1", "replace"), expected.encode("utf-8")
    )


def _require_cron_secret(x_cron_secret: Optional[str] = Header(default=None)) -> None:
    """Guard both routes on a shared secret sent as ``x-cron-secret``."""
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
    if not supplied or not _secret_matches(supplied, expected):
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
    session: Optional[AsyncSession] = Depends(optional_session),
    # The same connector *cache* the dashboard reads through — a factory now,
    # because a connector is bound to one user's credentials since F3 and this
    # job runs over every linked user. Still shared per user rather than rebuilt:
    # `IndMoneyConnector` remembers a definitive revocation, and a capture job
    # that built a fresh instance would re-learn that fact by making a doomed
    # call every night. Declared as a dependency so a test can substitute it the
    # same way it does for `/portfolio/*`.
    connector_factory: Callable[[str], PortfolioConnector] = Depends(connector_factory_dep),
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
    report = await capture_all(
        _require_database(session), connector_factory=connector_factory
    )
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
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """Drop raw payloads past their retention window.

    Only `snapshot_raw`. The daily totals and normalized holdings are kept
    forever — they are small, they are the actual history, and unlike the raw
    payloads they can never be re-acquired.
    """
    deleted = await prune_raw(_require_database(session), days=days)
    log.info("prune: deleted %d snapshot_raw rows older than %d days", deleted, days)
    return {"deleted": deleted, "days": days}


__all__ = ["CRON_SECRET_ENV", "CRON_SECRET_HEADER", "router"]
