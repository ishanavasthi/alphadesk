"""Portfolio endpoints for the dashboard (cards D1 + S1).

Thin by design: they call the M1 connector (`portfolio.connectors`), serialize
the **model's** vocabulary, and translate its typed failures into HTTP. Three
rules shape the whole file:

1. **The connector is the only source.** Nothing here imports
   `tools/ind_money.py`, and no vendor field name appears in this file — the
   boundary M1 established (`docs/SPECS/M1.md` §8) does not stop at
   `backend/portfolio/`.
2. **Every route is per user.** The user id comes from a verified Clerk session
   token (`portfolio_identity`); single-tenant dev serves ``"local"``. The
   interim C0 admin-secret path was removed at card L1 (the F3 §5 checklist).
3. **No source failure becomes a raw 500.** Every ``PortfolioSourceError`` maps
   to a status the frontend can act on, with a machine-readable ``code``.

**Money is serialized as strings**, never as JSON numbers. A `Decimal` rendered
through a float loses exactly the trailing digits a tabular figure is judged on,
and JSON has no decimal type; the frontend parses what it needs for maths and
prints the string otherwise. Dates are ISO-8601 UTC.

Rate limits are the reason these routes are singular. The source allows 15
calls/min per tool and 30/min globally, and a breakdown costs 2 — so
``/portfolio/allocation`` fetches exactly the one ``(asset_type, by)`` slice it
was asked for, and the whole-portfolio breakdowns the dashboard shows by default
come off the single ``/portfolio/summary`` snapshot call. Nothing here sweeps a
grid.

Issue #15 put a **read-through cache** in front of the three expensive reads
(`services/portfolio_cache.py`): the same questions asked again inside a short
window are answered from Postgres instead of the source. ``?fresh=1`` — the
Refresh button — is a true bypass that re-reads and rewrites the row, error
responses are never cached, and a deployment with no database behaves exactly as
it did before.

S1 added the two writes on this router — ``POST /portfolio/capture`` and the
fire-and-forget capture ``/summary`` starts when today's attributed day has no
row yet — plus a real ``/history``. Both stay behind the same identity as the
reads: they act on the caller's own account. The **cron-triggered** capture
lives on a separate router with a separate secret (`api/routes/internal.py`),
because a scheduled runner is not a person.

B10 introduced the first rows on this surface the *source* did not produce:
manually entered fixed deposits. They are merged in **additively and after the
cache** — appended to `/holdings?asset_type=FD`, summarized in `/summary`'s new
`manual` block — and never rewrite a vendor number. Their CRUD lives on its own
router (`api/routes/manual_fd.py`), sharing this one's identity dependency.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from collections.abc import Callable
from typing import Any, NoReturn, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import bearer_token, register_identity, verify_token
from tools.ind_money_auth import LOCAL_USER_ID, single_tenant_mode
from portfolio.connectors import (
    IndMoneyConnector,
    PortfolioConnector,
    StubConnector,
)
from portfolio.errors import (
    NonInrValue,
    NotLinked,
    PayloadShapeError,
    PortfolioSourceError,
    RateLimited,
    SourceReportedError,
    SourceUnavailable,
    UnsupportedAssetType,
    UnverifiedShapeError,
    UserScopeError,
)
from portfolio.models import (
    CURRENCY,
    Allocation,
    AllocationSlice,
    AssetType,
    BreakdownBy,
    Holding,
    PortfolioSnapshot,
    derive_pnl,
    is_us_exposure,
)
from services import manual_fd, portfolio_cache
from services.snapshots import (
    attributed_day,
    capture_if_missing,
    history_points,
    last_captured_at,
    movers_report,
    optional_session,
    schedule_capture_if_missing,
)

#: Which connector serves these routes. ``stub`` selects the invented demo
#: portfolio (`backend/tests/fixtures/demo/`) and is the only safe way to take a
#: screenshot of this dashboard — the default talks to the operator's real
#: linked account.
SOURCE_ENV = "ALPHADESK_PORTFOLIO_SOURCE"

#: Read-through cache windows (issue #15). Both are short enough that a reader
#: watching the market sees their own moves, and long enough that opening the
#: dashboard twice does not spend the source's per-minute budget twice. Holdings
#: get the longer one because a bucket walk is the expensive read — one per asset
#: type the snapshot reported. `/allocation` has no TTL here: its key carries the
#: attributed IST day, so it expires by name at the day boundary instead.
SUMMARY_TTL_SECONDS = 300
HOLDINGS_TTL_SECONDS = 900

#: `?fresh=1` — the Refresh button. A true bypass: skip the cache read, make the
#: source call, and write the result back so everyone else gets the new reading.
FRESH_QUERY = Query(False, description="Bypass the cache and re-read the source.")

_log = logging.getLogger(__name__)


async def _last_captured_at(
    session: Optional[AsyncSession], user_id: str
) -> Optional[datetime]:
    """`max(snapshot_days.captured_at)`, or None when there is no history yet.

    A database that is missing or unreachable answers None, not an error. This
    field decorates a page whose real content came from the source a moment ago;
    losing the decoration must not lose the page.
    """
    if session is None:
        return None
    try:
        return await last_captured_at(session, user_id)
    except Exception:  # noqa: BLE001 - see above
        _log.warning("last_captured_at unavailable", exc_info=True)
        return None


def _needs_capture(captured_at: Optional[datetime]) -> bool:
    """Whether the current attributed day is still missing a snapshot.

    Answered from ``max(captured_at)`` through the same IST helper the capture
    path files rows with, so the two can never disagree about which day a
    timestamp belongs to. Cheap enough to run on every page load, which is the
    point: the check has to be free or the third net stops being worth having.
    """
    if captured_at is None:
        return True
    return attributed_day(captured_at) < attributed_day(datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Who is asking?
# --------------------------------------------------------------------------- #
async def portfolio_identity(
    authorization: Optional[str] = Header(default=None),
    # `optional_session` is the *lazy* session dependency: it yields None when
    # `DATABASE_URL` is unset and otherwise hands over a session object without
    # connecting, so resolving it before the token costs nothing and cannot
    # 500. (`api.deps.current_user` needs the stricter ordering — it depends on
    # `async_session`, which raises on an unconfigured database — and gets it by
    # depending on `verified_claims` ahead of the session.)
    session: Optional[AsyncSession] = Depends(optional_session),
) -> str:
    """The user these routes serve: a verified Clerk id (or the local operator).

    **JWT-only in production as of card L1.** The interim C0 admin-secret path
    was removed here (the F3 §5 checklist): `NEXT_PUBLIC_AUTH_ENABLED` is now on,
    every visitor mints a Clerk token, and an admin-header request no longer
    authenticates anything. A caller with **no** verified identity gets the
    backend's 401 (`bearer_token` raises on a missing header), never a
    fall-through to an unowned credential.

    The one exception is single-tenant dev (`ALPHADESK_SINGLE_TENANT=1`, the
    operator's own machine, which has no Clerk instance): with no token it serves
    ``"local"``, the same identity that machine's broker link and snapshots are
    keyed under — matching `_lab_identity` and `_link_identity`. That flag stays
    unset in every deployed environment.
    """
    if not authorization and single_tenant_mode():
        return LOCAL_USER_ID
    claims = await asyncio.to_thread(verify_token, bearer_token(authorization))
    if session is None:
        # No database on this deployment: the token is still the identity,
        # there is simply nowhere to record that we have seen it.
        return str(claims["sub"])
    return await register_identity(session, claims)


router = APIRouter(prefix="/portfolio", tags=["portfolio"])

#: One connector per user id. `IndMoneyConnector` remembers that the source
#: definitively revoked *that user's* grant, and that memory is worth keeping —
#: but it is per user, so a process-wide singleton would have been a shared
#: credential wearing a cache's clothes.
_connectors: dict[str, PortfolioConnector] = {}

#: Ceiling on the cache. On overflow it is dropped wholesale: the only cost is
#: re-learning revocation states, and an LRU here would be machinery guarding a
#: cheap object.
_CONNECTOR_CACHE_MAX = 1000


def _build_connector(user_id: str) -> PortfolioConnector:
    if (os.environ.get(SOURCE_ENV) or "").strip().lower() == "stub":
        return StubConnector()
    return IndMoneyConnector(user_id=user_id)


def get_connector(user_id: str) -> PortfolioConnector:
    """The connector serving ``user_id``, created on first use.

    **Takes the user id.** The pre-F3 signature took nothing and returned the
    one connector the process had, which is how a single credential ended up
    answering for every caller. Any new call site that cannot name a user is a
    call site that should not be reading holdings.
    """
    connector = _connectors.get(user_id)
    if connector is None:
        if len(_connectors) >= _CONNECTOR_CACHE_MAX:
            _connectors.clear()
        connector = _build_connector(user_id)
        _connectors[user_id] = connector
    return connector


def connector_for_request(
    user_id: str = Depends(portfolio_identity),
) -> PortfolioConnector:
    """FastAPI wiring for :func:`get_connector`. One per request, per user."""
    return get_connector(user_id)


def connector_factory() -> Callable[[str], PortfolioConnector]:
    """:func:`get_connector` itself, as a dependency.

    The batch snapshot job has no single user, so it needs the *factory* rather
    than a connector. Named rather than a lambda so a test can override it —
    an anonymous dependency cannot be looked up in `dependency_overrides`.
    """
    return get_connector


def reset_connector() -> None:
    """Drop every cached connector (tests, and a source switch in dev)."""
    _connectors.clear()


def evict_connector(user_id: str) -> None:
    """Drop one user's cached connector (card L1, delete-my-data).

    The connector holds a reference to the user's `AuthStore`, which caches
    decrypted tokens. When the account is deleted the connector must go too, or a
    later request under a re-used id could be served by a stale one carrying
    credentials that no longer belong to anyone.
    """
    _connectors.pop(user_id, None)


# --------------------------------------------------------------------------- #
# Serialization — Decimal as string, enums as their value, no `raw` anywhere
# --------------------------------------------------------------------------- #
def _num(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(value, "f")


def _slice_json(item: AllocationSlice) -> dict[str, Any]:
    asset_type = item.asset_type
    return {
        "label": item.label,
        "asset_type": asset_type.value if asset_type is not None else None,
        "asset_type_raw": item.asset_type_raw,
        "invested_amount": _num(item.invested_amount),
        "current_value": _num(item.current_value),
        "pnl": _num(item.pnl),
        "pnl_pct": _num(item.pnl_pct),
        "weight_pct": _num(item.weight_pct),
        "us_exposure": (
            is_us_exposure(asset_type, item.asset_type_raw) if asset_type is not None else False
        ),
        "currency": item.currency,
    }


def _holding_json(item: Holding) -> dict[str, Any]:
    """One row. ``Holding.raw`` is deliberately **not** serialized — it is the
    source's own row, kept for forensics, and shipping it to a browser would put
    vendor field names (and unmapped material) back above the boundary."""
    return {
        "source": item.source,
        "external_id": item.external_id,
        "asset_type": item.asset_type.value,
        "asset_type_raw": item.asset_type_raw,
        "symbol": item.symbol,
        "name": item.name,
        "isin": item.isin,
        "units": _num(item.units),
        "avg_cost": _num(item.avg_cost),
        "invested_amount": _num(item.invested_amount),
        "current_price": _num(item.current_price),
        "current_value": _num(item.current_value),
        "pnl": _num(item.pnl),
        "pnl_pct": _num(item.pnl_pct),
        "us_exposure": item.is_us_exposure,
        "currency": item.currency,
        "as_of": item.as_of.isoformat(),
    }


def _snapshot_json(
    snapshot: PortfolioSnapshot,
    link_health: str,
    captured_at: Optional[datetime] = None,
    user_id: str = "",
) -> dict[str, Any]:
    pnl, pnl_pct = derive_pnl(snapshot.gross_value, snapshot.invested_total)
    return {
        "user_id": user_id,
        "source": snapshot.source,
        "as_of": snapshot.as_of.isoformat(),
        "currency": snapshot.currency,
        "net_worth": _num(snapshot.net_worth),
        # The source's own gross figure. Named for what the dashboard calls it.
        "current_value": _num(snapshot.gross_value),
        "invested_total": _num(snapshot.invested_total),
        "liabilities_total": _num(snapshot.liabilities_total),
        # Nullable on purpose: with no cost basis there is no return, and a
        # computed 0 or -100% here would be fabricated (M1 §3).
        "pnl": _num(pnl),
        "pnl_pct": _num(pnl_pct),
        # All four breakdowns ride the same single snapshot call — free, and the
        # only whole-portfolio sector/cap figures that exist (the breakdown tool
        # is per-asset-type). Drill-downs go through /portfolio/allocation.
        "by_asset_type": [_slice_json(s) for s in snapshot.by_asset_type],
        "by_asset_class": [_slice_json(s) for s in snapshot.by_asset_class],
        "by_sector": [_slice_json(s) for s in snapshot.by_sector],
        "by_market_cap": [_slice_json(s) for s in snapshot.by_market_cap],
        "link_health": link_health,
        # `max(snapshot_days.captured_at)` for this user, or null when nothing
        # has ever been captured. The dashboard derives its staleness banner
        # from this — null is "no history yet", not "history is broken".
        "last_captured_at": captured_at.isoformat() if captured_at else None,
    }


def _allocation_json(allocation: Allocation) -> dict[str, Any]:
    return {
        "source": allocation.source,
        "asset_type": allocation.asset_type.value,
        "by": allocation.by.value,
        "as_of": allocation.as_of.isoformat(),
        "currency": allocation.currency,
        "slices": [_slice_json(s) for s in allocation.slices],
    }


# --------------------------------------------------------------------------- #
# Typed source failures -> HTTP
# --------------------------------------------------------------------------- #
#: Messages are fixed strings, never the exception's text: a source's own error
#: body can carry payload fragments, and this response is public to whoever
#: holds the admin secret today and to every logged-in user after F3.
def _fail(exc: PortfolioSourceError) -> NoReturn:
    if isinstance(exc, NotLinked):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_linked",
                "message": "No usable IND Money link. Connect the account to see holdings.",
                "connect": {"method": "POST", "path": "/auth/login"},
            },
        )
    if isinstance(exc, RateLimited):
        retry_after = exc.retry_after if exc.retry_after and exc.retry_after > 0 else 5
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": "The source is rate-limiting this account; the call was not made.",
                "retry_after": retry_after,
                "scope": exc.scope,
            },
            headers={"Retry-After": str(int(retry_after) or 1)},
        )
    if isinstance(exc, UnsupportedAssetType):
        # A client asked for something this source cannot be queried for
        # (e.g. the UNKNOWN bucket). That is a bad request, not an outage.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_asset_type",
                "message": "This source cannot be queried for that asset type.",
            },
        )
    if isinstance(exc, UserScopeError):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "user_scope",
                "message": "This connector is bound to a different user.",
            },
        )
    if isinstance(exc, UnverifiedShapeError):
        # The IND_STOCK boundary (M1 §7). The dashboard renders a labeled
        # boundary state for exactly this code — never an empty table, which
        # would read as "you hold no Indian stocks".
        raise HTTPException(
            status_code=502,
            detail={
                "code": "unverified_shape",
                "message": (
                    "The source returned a row shape this integration has never "
                    "verified, so those rows are withheld rather than guessed at."
                ),
            },
        )
    if isinstance(exc, NonInrValue):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "non_inr",
                "message": (
                    "The source reported a non-INR value. Cross-currency totals "
                    "are not computed, so the response is withheld."
                ),
            },
        )
    if isinstance(exc, PayloadShapeError):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "payload_shape",
                "message": "The source returned a payload this integration cannot read.",
            },
        )
    if isinstance(exc, (SourceUnavailable, SourceReportedError)):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "source_unavailable",
                "message": "The portfolio source could not be reached.",
            },
        )
    raise HTTPException(
        status_code=502,
        detail={
            "code": "source_error",
            "message": "The portfolio source failed.",
        },
    )


def _asset_type(value: str) -> AssetType:
    coerced = AssetType.coerce(value)
    if coerced is AssetType.UNKNOWN and (value or "").strip().upper() != AssetType.UNKNOWN.value:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_asset_type",
                "message": f"{value!r} is not an asset type this API knows.",
            },
        )
    return coerced


def _breakdown_by(value: str) -> BreakdownBy:
    try:
        return BreakdownBy(value.strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_breakdown",
                "message": f"{value!r} is not a breakdown this API knows.",
            },
        )


# --------------------------------------------------------------------------- #
# Manually entered holdings (card B10) — additive, never cached
# --------------------------------------------------------------------------- #
#: Manual rows are merged into the responses below **after** the read-through
#: cache, never into it. Two reasons, and both matter:
#:
#: 1. A manual FD's value is recomputed from its terms on every read. Baking one
#:    into a 15-minute cache entry would freeze an accrual that is supposed to be
#:    the one number on this page that is always current.
#: 2. The cache is keyed on the *source's* answer. Writing a user-authored row
#:    into it would mean every write to `/portfolio/fds` had to invalidate a
#:    cache key it has no business knowing about — machinery that merging after
#:    the fact removes entirely.
#:
#: Additive is the whole posture: nothing here rewrites, reconciles against or
#: repairs a vendor figure. Repairing the vendor's own FD bucket is card B9.
async def _manual_holdings(
    session: Optional[AsyncSession], user_id: str
) -> list[dict[str, Any]]:
    """``user_id``'s manual rows, serialized. Never raises — merging is additive.

    A failure here must not take down a holdings page the source already
    answered, so it degrades to "no manual rows" with a warning, exactly like
    `last_captured_at` does for the summary.
    """
    if session is None:
        return []
    try:
        rows = await manual_fd.as_holdings(session, user_id)
    except Exception:  # noqa: BLE001 - see above
        _log.warning("manual holdings unavailable", exc_info=True)
        return []
    return [_holding_json(h) for h in rows]


async def _manual_block(
    session: Optional[AsyncSession], user_id: str
) -> dict[str, Any]:
    """The summary's additive ``manual`` block: total accrued value and a count.

    Computed per request and **never** cached, for the same reason as above. No
    vendor-derived field is touched: `net_worth`, `by_asset_type` and the rest
    pass through byte-identical, and the frontend does the labelled addition
    ("incl. Rs X manual FDs") where a reader can see it happen.
    """
    if session is None:
        return {"total": "0", "fd_count": 0}
    try:
        total, count = await manual_fd.manual_total(session, user_id)
    except Exception:  # noqa: BLE001 - additive; it never fails the page
        _log.warning("manual totals unavailable", exc_info=True)
        return {"total": "0", "fd_count": 0}
    return {"total": _num(total), "fd_count": count}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@router.get("/summary")
async def summary(
    fresh: bool = FRESH_QUERY,
    user_id: str = Depends(portfolio_identity),
    connector: PortfolioConnector = Depends(connector_for_request),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """Headline totals, the snapshot's four breakdowns, and link health.

    One source call, plus one cheap DB read for ``last_captured_at`` — or, within
    the cache window, no source call at all (issue #15).

    **Also the third net.** If today's attributed day has no snapshot row, this
    fires a capture in the background — after the response is composed, never
    blocking it, and never twice at once (`single_flight`). The two scheduled
    runs are the plan; this is what covers the week GitHub silently disables the
    workflow, because the moment somebody opens the dashboard is the moment the
    source can still be asked about today. That net hangs off a **real** read: a
    cache hit made no source call, so it has learned nothing new about today.

    Card B10 adds one **additive** top-level block, ``manual``, carrying the
    total accrued value of the user's manually entered fixed deposits and how
    many there are. It is computed per request on both paths (cache hit and
    miss) and cached nowhere. Every vendor-derived field — ``net_worth``,
    ``by_asset_type``, all of it — passes through byte-identical: this module
    never recomputes the source's arithmetic, and a manual holding is a labelled
    addition the frontend makes visible, not a silent adjustment made here.
    """
    key = portfolio_cache.summary_key()
    if not fresh:
        cached = await portfolio_cache.get(
            session, user_id, key, max_age=SUMMARY_TTL_SECONDS
        )
        if cached is not None:
            # The one field that is *not* served from the cache. It comes from
            # this deployment's own database, costs a single indexed read, and is
            # what the staleness banner is derived from — a capture that landed
            # since the payload was cached has to show up immediately, or the page
            # tells someone their history stopped when it did not.
            captured_at = await _last_captured_at(session, user_id)
            cached["last_captured_at"] = captured_at.isoformat() if captured_at else None
            # Manual deposits are recomputed per request and never cached (B10).
            return {**cached, "manual": await _manual_block(session, user_id)}

    try:
        health = await connector.link_health(user_id)
        snapshot = await connector.fetch_snapshot(user_id)
    except PortfolioSourceError as exc:
        _fail(exc)

    captured_at = await _last_captured_at(session, user_id)
    if session is not None and _needs_capture(captured_at):
        schedule_capture_if_missing(user_id, connector)
    payload = _snapshot_json(snapshot, health.value, captured_at, user_id)
    await portfolio_cache.put(session, user_id, key, payload, as_of=snapshot.as_of)
    # After the cache write, deliberately: the `manual` block is per-request.
    return {**payload, "manual": await _manual_block(session, user_id)}


@router.post("/capture")
async def capture(
    user_id: str = Depends(portfolio_identity),
    connector: PortfolioConnector = Depends(connector_for_request),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """Capture today's attributed day now — the top bar's "Capture snapshot".

    The same opportunistic path `/summary` fires in the background, but awaited,
    because a reader who pressed a button is owed an answer rather than a
    hopeful spinner. It shares the single-flight guard with that background
    task, so pressing the button while one is already running reports
    ``in_flight`` instead of making a second burst of source calls.

    Idempotent by construction: the day already having a row answers
    ``already_captured``, not a duplicate.
    """
    if session is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "no_database",
                "message": "This deployment has no database configured, so nothing can be captured.",
            },
        )
    # The request's own session, not one this call opens: an awaited capture is
    # inside the request's scope, so it should use the request's transaction.
    # (The fire-and-forget net in `/summary` is the opposite case and opens its
    # own, because a request-scoped session is closed by the time it runs.)
    outcome = await capture_if_missing(
        user_id, connector=connector, session=session
    )
    if outcome is None:
        return {"status": "in_flight", "captured_on": None}
    return {
        "status": outcome.status,
        "captured_on": outcome.captured_on.isoformat(),
        "holdings": outcome.holdings,
        "reason": outcome.reason,
        "buckets_failed": [f.as_dict() for f in outcome.buckets_failed],
    }


@router.get("/holdings")
async def holdings(
    asset_type: str = Query(..., description="One of the 16 queryable asset types."),
    fresh: bool = FRESH_QUERY,
    user_id: str = Depends(portfolio_identity),
    connector: PortfolioConnector = Depends(connector_for_request),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """Rows for **one** asset type.

    Singular by design: the source is queried per asset type and rate-limits per
    tool, so the caller asks for the buckets its snapshot actually reported
    rather than walking the enum. An asset type the user holds nothing in
    returns ``[]`` — a valid answer, not an error.

    Cached per asset type (issue #15), which is what makes a second visit to
    Holdings free: one bucket walk is most of the source's per-minute budget.

    **FD is the one bucket with a second source.** The user's manually entered
    deposits (card B10) are appended *after* the cache read and write, so they
    are always freshly valued, never baked into the vendor's cached answer, and
    a write to `/portfolio/fds` shows up on the very next read with no cache
    invalidation anywhere. They carry ``source: "manual"``; every vendor row is
    untouched, and every other asset type is byte-identical to before.
    """
    parsed = _asset_type(asset_type)
    key = portfolio_cache.holdings_key(parsed.value)
    payload: Optional[dict[str, Any]] = None
    if not fresh:
        payload = await portfolio_cache.get(
            session, user_id, key, max_age=HOLDINGS_TTL_SECONDS
        )
    if payload is None:
        try:
            rows = await connector.fetch_holdings(user_id, parsed)
        except PortfolioSourceError as exc:
            _fail(exc)
        payload = {
            "asset_type": parsed.value,
            "currency": CURRENCY,
            "holdings": [_holding_json(h) for h in rows],
        }
        await portfolio_cache.put(
            session,
            user_id,
            key,
            payload,
            as_of=rows[0].as_of if rows else None,
        )
    if parsed is AssetType.FD:
        manual = await _manual_holdings(session, user_id)
        if manual:
            # A new dict, not an in-place append: `payload` may be the object
            # just handed to the cache writer, and a manual row must never end
            # up inside a cached vendor answer.
            payload = {**payload, "holdings": [*payload["holdings"], *manual]}
    return payload


@router.get("/allocation")
async def allocation(
    asset_type: str = Query(..., description="One of the 16 queryable asset types."),
    by: str = Query(..., description="assets | sector | market_cap"),
    fresh: bool = FRESH_QUERY,
    user_id: str = Depends(portfolio_identity),
    connector: PortfolioConnector = Depends(connector_for_request),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """One ``(asset_type, by)`` breakdown, fetched lazily.

    **Never sweep the grid.** 16 asset types x 3 breakdowns is 48 calls at a
    cost of 2 each against a 15/min per-tool budget — it trips after seven.

    Cached **for the attributed IST day** (issue #15) rather than on a clock TTL:
    a drill-down is a composition, which moves when the market moves and not
    between two page loads, and one that has been read once today should be
    instant for the rest of it. The day is in the cache key, so the row expires
    by name — through the same helper capture attribution uses, never a UTC
    "today".
    """
    parsed = _asset_type(asset_type)
    parsed_by = _breakdown_by(by)
    key = portfolio_cache.allocation_key(
        parsed.value, parsed_by.value, attributed_day(datetime.now(timezone.utc))
    )
    if not fresh:
        cached = await portfolio_cache.get(session, user_id, key)
        if cached is not None:
            return cached
    try:
        result = await connector.fetch_allocation(user_id, parsed, parsed_by)
    except PortfolioSourceError as exc:
        _fail(exc)
    payload = _allocation_json(result)
    await portfolio_cache.put(session, user_id, key, payload, as_of=result.as_of)
    return payload


@router.get("/history")
async def history(
    days: int = Query(90, ge=1, le=1825, description="Window length in days."),
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """Net-worth history from the captured daily snapshots.

    One point per attributed IST calendar day that was actually captured. There
    is **no interpolation and no forward-fill**: a gap in the line is a day the
    job did not run, and smoothing it over would erase the one signal that says
    so. The source is point-in-time, so a missing day cannot be recovered — it
    can only be drawn honestly or hidden.

    Degrades to an empty series (never a 500) when no database is configured or
    the query fails: the live figures on this dashboard do not depend on
    Postgres and must not start doing so here.
    """
    if session is None:
        return {
            "points": [],
            "last_captured_at": None,
            "days": days,
            "currency": CURRENCY,
            "note": "No database is configured, so no history is being captured.",
        }
    try:
        points = await history_points(session, user_id, days=days)
        captured_at = await last_captured_at(session, user_id)
    except Exception:  # noqa: BLE001 - history is additive; it never fails the page
        _log.warning("portfolio history unavailable", exc_info=True)
        return {
            "points": [],
            "last_captured_at": None,
            "days": days,
            "currency": CURRENCY,
            "note": "History could not be read from the database.",
        }
    return {
        "points": [
            {"date": p.captured_on.isoformat(), "net_worth": _num(p.total_value)}
            for p in points
        ],
        "last_captured_at": captured_at.isoformat() if captured_at else None,
        "days": days,
        "currency": CURRENCY,
        "note": (
            None
            if points
            else "No daily snapshots have been captured yet; the first one starts the line."
        ),
    }


def _mover_json(row: Any) -> dict[str, Any]:
    return {
        "source": row.source,
        "external_id": row.external_id,
        "asset_type": row.asset_type,
        "name": row.name,
        "symbol": row.symbol,
        "basis": row.basis,
        "start_price": _num(row.start_price),
        "end_price": _num(row.end_price),
        "start_value": _num(row.start_value),
        "end_value": _num(row.end_value),
        "change_abs": _num(row.change_abs),
        "change_pct": _num(row.change_pct),
        "currency": row.currency,
    }


def _day(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


@router.get("/movers")
async def movers(
    from_day: Optional[date] = Query(
        None, alias="from", description="Window start (YYYY-MM-DD). Default: 7 days before `to`."
    ),
    to_day: Optional[date] = Query(
        None, alias="to", description="Window end (YYYY-MM-DD). Default: the latest captured day."
    ),
    limit: int = Query(5, ge=1, le=50, description="Cap on each of gainers and losers."),
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """What moved most between two captured days — read from history, not the source.

    Descriptive arithmetic over the user's own snapshots (card B8): it ranks what
    *did* happen and rates, recommends and projects nothing. No source call is
    made here at all, which is why it can afford to answer a five-year window.

    Three honesty rules do the work, all of them in `services.snapshots`:
    percentages come from `current_price` so a top-up never reads as a rally;
    unpriced balances (savings, deposits) land in ``flows`` and are never ranked
    as movers; and a position present on only one of the two days is listed as
    opened or closed rather than rendered as ±100%.

    Presets (1D/1W/1M/3M/YTD) are a frontend concern — this takes dates.

    Degrades to empty lists with a note (never a 500) when no database is
    configured or the query fails, exactly like ``/history``.
    """
    empty = {
        "requested": {"from": _day(from_day), "to": _day(to_day)},
        "compared": {"from": None, "to": None},
        "gainers": [],
        "losers": [],
        "flows": [],
        "opened": [],
        "closed": [],
        "excluded": [],
        "limit": limit,
        "currency": CURRENCY,
    }
    if session is None:
        return {
            **empty,
            "note": "No database is configured, so no history is being captured.",
        }
    try:
        report = await movers_report(
            session, user_id, from_day=from_day, to_day=to_day, limit=limit
        )
    except Exception:  # noqa: BLE001 - movers are additive; they never fail the page
        _log.warning("portfolio movers unavailable", exc_info=True)
        return {**empty, "note": "Movers could not be read from the database."}
    return {
        "requested": {
            "from": _day(report.requested_from),
            "to": _day(report.requested_to),
        },
        "compared": {
            "from": _day(report.compared_from),
            "to": _day(report.compared_to),
        },
        "note": report.note,
        "gainers": [_mover_json(r) for r in report.gainers],
        "losers": [_mover_json(r) for r in report.losers],
        "flows": [_mover_json(r) for r in report.flows],
        "opened": [_mover_json(r) for r in report.opened],
        "closed": [_mover_json(r) for r in report.closed],
        "excluded": [dict(item) for item in report.excluded],
        "limit": limit,
        "currency": CURRENCY,
    }


__all__ = [
    "SOURCE_ENV",
    "connector_factory",
    "connector_for_request",
    "evict_connector",
    "get_connector",
    "portfolio_identity",
    "reset_connector",
    "router",
]
