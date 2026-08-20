"""`/portfolio/fds` — the manual fixed-deposit CRUD surface (card B10).

The first endpoints on this dashboard that *accept* financial data rather than
report it. Everything else under `/portfolio/*` is a rendering of what the
source said; these four routes own rows the user authored, which changes two
things about the posture:

**No in-memory fallback.** With no `DATABASE_URL`, reads degrade to an empty
list with a note (like `/history` and `/movers` — the page must not break), but
**writes answer 503 `no_database`**. The Lab's watchlist deliberately falls back
to a process dict; a deposit must not. A user who types their terms into a form,
sees a success toast, and loses the row on the next restart has been lied to,
and the failure is invisible until the data is gone.

**Another user's id is a 404, never a 403.** Every query is scoped on
`user_id` in its `WHERE` clause (`services.manual_fd`), so a row that is not the
caller's is never loaded and existence is never leaked — the same rule the Lab
follows for runs (F4 §2).

Identity and serialization match the rest of the portfolio surface exactly:
`portfolio_identity` (a verified Clerk token, or `"local"` under
`ALPHADESK_SINGLE_TENANT=1`; **401** with neither), `optional_session`, and
money as **strings** via `_num`. The computed fields — `current_value`,
`accrued_interest`, `maturity_value`, `matured`, `days_to_maturity` — are
recomputed on **every** read and stored nowhere. That is the whole feature: the
user enters terms once, and the value tracks itself.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.portfolio import _num, portfolio_identity
from db.models import ManualFd
from services import manual_fd as service
from services.snapshots import optional_session

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio/fds", tags=["portfolio"])

#: Served instead of a 500 when the deployment has no database. The dashboard
#: renders the card's empty state and this line explains why it is empty.
NO_DATABASE_NOTE = (
    "No database is configured, so manual fixed deposits cannot be stored."
)

#: Literal rather than `str`: an unknown compounding convention is a **422 from
#: the schema**, before any code runs, and the accepted values show up in
#: `/docs` for free.
Compounding = Literal["monthly", "quarterly", "half_yearly", "yearly", "simple"]


def _no_database() -> HTTPException:
    """The write-path refusal. Same shape as `POST /portfolio/capture`'s."""
    return HTTPException(
        status_code=503,
        detail={
            "code": "no_database",
            "message": (
                "This deployment has no database configured, so a fixed deposit "
                "cannot be saved."
            ),
        },
    )


def _invalid_terms(message: str) -> HTTPException:
    """A 422 that the schema could not express — the merged-PATCH date check."""
    return HTTPException(
        status_code=422,
        detail={"code": "invalid_terms", "message": message},
    )


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class _FdBody(BaseModel):
    """Shared config. `extra="forbid"` so a typo'd field is a 422, not a no-op
    the user reads as a successful edit."""

    model_config = ConfigDict(extra="forbid")


class FdCreate(_FdBody):
    """A new deposit. Every constraint here is a guard against a typo, not a
    view about what a sensible deposit looks like."""

    label: str = Field(min_length=1, max_length=120)
    principal: Decimal = Field(gt=0)
    #: Annual percent. The ceiling catches `7.25` typed as `725`; it is not a
    #: judgement about what rate a bank may offer.
    rate_pct: Decimal = Field(gt=0, le=service.MAX_RATE_PCT)
    compounding: Compounding = service.DEFAULT_COMPOUNDING
    start_date: date
    maturity_date: date

    @field_validator("label")
    @classmethod
    def _trim(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("label cannot be blank")
        return trimmed

    @model_validator(mode="after")
    def _term_is_positive(self) -> "FdCreate":
        if self.start_date >= self.maturity_date:
            raise ValueError("start_date must be before maturity_date")
        return self


class FdPatch(_FdBody):
    """A partial edit. Any field may change — a mistyped rate or date is the
    most likely reason this dialog is ever opened.

    Fields left out are unchanged, and an explicit ``null`` is read the same
    way: there is no field here whose value can be cleared, so "null" can only
    mean "leave it". The `start < maturity` check needs the *merged* row and
    therefore happens in the route, not here."""

    label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    principal: Optional[Decimal] = Field(default=None, gt=0)
    rate_pct: Optional[Decimal] = Field(default=None, gt=0, le=service.MAX_RATE_PCT)
    compounding: Optional[Compounding] = None
    start_date: Optional[date] = None
    maturity_date: Optional[date] = None

    @field_validator("label")
    @classmethod
    def _trim(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("label cannot be blank")
        return trimmed

    def changes(self) -> dict[str, Any]:
        return {
            field: value
            for field, value in self.model_dump(exclude_unset=True).items()
            if value is not None
        }


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def _fd_json(fd: ManualFd, as_of: date) -> dict[str, Any]:
    """One row: the stored terms, plus the valuation derived from them *now*.

    The two halves are deliberately in one object. A client that received only
    the terms would have to re-implement the accrual to show a value, and two
    implementations of the same formula is how a screen ends up disagreeing with
    the API about someone's money.
    """
    computed = service.value_row(fd, as_of)
    return {
        "id": fd.id,
        "label": fd.label,
        "principal": _num(Decimal(fd.principal)),
        "rate_pct": _num(Decimal(fd.rate_pct)),
        "compounding": fd.compounding,
        "start_date": fd.start_date.isoformat(),
        "maturity_date": fd.maturity_date.isoformat(),
        "current_value": _num(computed.current_value),
        "accrued_interest": _num(computed.accrued_interest),
        "maturity_value": _num(computed.maturity_value),
        "matured": computed.matured,
        "days_to_maturity": computed.days_to_maturity,
        "created_at": fd.created_at.isoformat() if fd.created_at else None,
        "updated_at": fd.updated_at.isoformat() if fd.updated_at else None,
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@router.get("")
async def list_fds(
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """The caller's deposits, soonest maturity first, valued as of today (IST).

    Degrades to an empty list with a note rather than a 500 when there is no
    database — this card sits on a page whose live figures do not depend on
    Postgres, and it must not be the thing that breaks it.
    """
    if session is None:
        return {"fds": [], "note": NO_DATABASE_NOTE}
    today = service.today_ist()
    rows = await service.list_fds(session, user_id)
    return {"fds": [_fd_json(fd, today) for fd in rows], "note": None}


@router.post("", status_code=201)
async def create_fd(
    body: FdCreate,
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """Record a deposit. 201 with the row, valued immediately."""
    if session is None:
        raise _no_database()
    fd = await service.create_fd(
        session,
        user_id,
        label=body.label,
        principal=body.principal,
        rate_pct=body.rate_pct,
        compounding=body.compounding,
        start_date=body.start_date,
        maturity_date=body.maturity_date,
    )
    return _fd_json(fd, service.today_ist())


@router.patch("/{fd_id}")
async def update_fd(
    fd_id: str,
    body: FdPatch,
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """Edit a deposit's terms; the valuation moves with them on the next read."""
    if session is None:
        raise _no_database()
    existing = await service.get_fd(session, user_id, fd_id)
    if existing is None:
        # 404, never 403: another user's id must be indistinguishable from one
        # that was never issued.
        raise HTTPException(status_code=404, detail="Unknown fixed deposit")

    changes = body.changes()
    # The date rule needs the row as it *will* be, which the request body alone
    # cannot see — patching only `maturity_date` can still invert the term.
    start = changes.get("start_date", existing.start_date)
    maturity = changes.get("maturity_date", existing.maturity_date)
    if start >= maturity:
        raise _invalid_terms("start_date must be before maturity_date")

    fd = await service.update_fd(session, user_id, fd_id, changes)
    if fd is None:  # pragma: no cover - the row was there a statement ago
        raise HTTPException(status_code=404, detail="Unknown fixed deposit")
    return _fd_json(fd, service.today_ist())


@router.delete("/{fd_id}", status_code=204)
async def delete_fd(
    fd_id: str,
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> None:
    """Remove a deposit. 204 on success, 404 if it is not the caller's."""
    if session is None:
        raise _no_database()
    if not await service.delete_fd(session, user_id, fd_id):
        raise HTTPException(status_code=404, detail="Unknown fixed deposit")


__all__ = ["NO_DATABASE_NOTE", "FdCreate", "FdPatch", "router"]
