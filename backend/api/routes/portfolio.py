"""Read-only portfolio endpoints for the D1 dashboard.

Four routes, all of them thin: they call the M1 connector
(`portfolio.connectors`), serialize the **model's** vocabulary, and translate
its typed failures into HTTP. Three rules shape the whole file:

1. **The connector is the only source.** Nothing here imports
   `tools/ind_money.py`, and no vendor field name appears in this file — the
   boundary M1 established (`docs/SPECS/M1.md` §8) does not stop at
   `backend/portfolio/`.
2. **Every route is gated** by the interim C0 admin secret. These endpoints
   serve the operator's *real* portfolio under a hard-coded ``user_id`` and no
   per-user auth exists until F3 — see :func:`_admin_gate`.
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
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, NoReturn, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from portfolio.connectors import (
    LOCAL_USER_ID,
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

#: Which connector serves these routes. ``stub`` selects the invented demo
#: portfolio (`backend/tests/fixtures/demo/`) and is the only safe way to take a
#: screenshot of this dashboard — the default talks to the operator's real
#: linked account.
SOURCE_ENV = "ALPHADESK_PORTFOLIO_SOURCE"


def _admin_gate(
    x_alphadesk_admin_secret: Optional[str] = Header(default=None),
) -> None:
    """Interim exposure gate — the C0 admin secret, on every portfolio route.

    Reuses ``api.main._require_admin`` rather than re-deriving the comparison:
    one gate, one fail-closed rule, one place to delete when F3 lands per-user
    auth. The import is deferred because `api.main` mounts this router, so a
    module-level import would be circular.

    Why a gate at all on read-only routes: until F3 there is no user identity
    anywhere in the stack, and these routes serve **the operator's real
    holdings** under the constant ``user_id="local"``. Ungated, deploying this
    dashboard would publish one person's net worth to anyone who can reach the
    URL. Single-tenant dev mode (``ALPHADESK_SINGLE_TENANT=1``, the operator's
    own machine) bypasses it exactly as it does for connect/disconnect.
    """
    from api.main import _require_admin

    _require_admin(x_alphadesk_admin_secret)


router = APIRouter(prefix="/portfolio", tags=["portfolio"], dependencies=[Depends(_admin_gate)])

_connector: Optional[PortfolioConnector] = None


def _build_connector() -> PortfolioConnector:
    if (os.environ.get(SOURCE_ENV) or "").strip().lower() == "stub":
        return StubConnector()
    return IndMoneyConnector(user_id=LOCAL_USER_ID)


def get_connector() -> PortfolioConnector:
    """The process-wide connector.

    Deliberately a singleton: ``IndMoneyConnector`` remembers that the source
    definitively revoked our grant, and that memory is worthless if every
    request builds a fresh instance that has to learn it again.
    """
    global _connector
    if _connector is None:
        _connector = _build_connector()
    return _connector


def reset_connector() -> None:
    """Drop the cached connector (tests, and a source switch in dev)."""
    global _connector
    _connector = None


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


def _snapshot_json(snapshot: PortfolioSnapshot, link_health: str) -> dict[str, Any]:
    pnl, pnl_pct = derive_pnl(snapshot.gross_value, snapshot.invested_total)
    return {
        "user_id": LOCAL_USER_ID,
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
        # Snapshots land in S1. Until then this is honestly null rather than
        # "now", which would claim a history that does not exist.
        "last_captured_at": None,
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
# Routes
# --------------------------------------------------------------------------- #
@router.get("/summary")
async def summary(connector: PortfolioConnector = Depends(get_connector)) -> dict[str, Any]:
    """Headline totals, the snapshot's four breakdowns, and link health.

    One source call. ``last_captured_at`` is null until S1 captures the first
    daily snapshot.
    """
    try:
        health = await connector.link_health(LOCAL_USER_ID)
        snapshot = await connector.fetch_snapshot(LOCAL_USER_ID)
    except PortfolioSourceError as exc:
        _fail(exc)
    return _snapshot_json(snapshot, health.value)


@router.get("/holdings")
async def holdings(
    asset_type: str = Query(..., description="One of the 16 queryable asset types."),
    connector: PortfolioConnector = Depends(get_connector),
) -> dict[str, Any]:
    """Rows for **one** asset type.

    Singular by design: the source is queried per asset type and rate-limits per
    tool, so the caller asks for the buckets its snapshot actually reported
    rather than walking the enum. An asset type the user holds nothing in
    returns ``[]`` — a valid answer, not an error.
    """
    parsed = _asset_type(asset_type)
    try:
        rows = await connector.fetch_holdings(LOCAL_USER_ID, parsed)
    except PortfolioSourceError as exc:
        _fail(exc)
    return {
        "asset_type": parsed.value,
        "currency": CURRENCY,
        "holdings": [_holding_json(h) for h in rows],
    }


@router.get("/allocation")
async def allocation(
    asset_type: str = Query(..., description="One of the 16 queryable asset types."),
    by: str = Query(..., description="assets | sector | market_cap"),
    connector: PortfolioConnector = Depends(get_connector),
) -> dict[str, Any]:
    """One ``(asset_type, by)`` breakdown, fetched lazily.

    **Never sweep the grid.** 16 asset types x 3 breakdowns is 48 calls at a
    cost of 2 each against a 15/min per-tool budget — it trips after seven.
    """
    parsed = _asset_type(asset_type)
    parsed_by = _breakdown_by(by)
    try:
        result = await connector.fetch_allocation(LOCAL_USER_ID, parsed, parsed_by)
    except PortfolioSourceError as exc:
        _fail(exc)
    return _allocation_json(result)


@router.get("/history")
async def history(
    days: int = Query(90, ge=1, le=1825, description="Window length in days."),
) -> dict[str, Any]:
    """Net-worth history — honestly empty until S1 captures daily snapshots.

    The shape is final: S1 fills ``points`` with ``{date, net_worth}`` objects
    and sets ``last_captured_at``. Nothing else about this response, or about
    the chart that reads it, has to change. Returning a synthesized line here
    would be inventing a past this deployment does not have.
    """
    return {
        "points": [],
        "last_captured_at": None,
        "days": days,
        "currency": CURRENCY,
        "note": "Daily snapshots start with card S1; no history has been captured yet.",
    }


__all__ = ["SOURCE_ENV", "get_connector", "reset_connector", "router"]
