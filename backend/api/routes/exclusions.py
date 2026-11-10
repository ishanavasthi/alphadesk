"""`/portfolio/exclusions` — holdings the user leaves out of every figure.

The source misreports some rows (#65: fixed deposits reported at a fraction of
their principal), and a user who has entered the real deposits by hand (B10)
needs a way to say "ignore that vendor row". These three routes store that
choice; `services.exclusions` documents where it is applied.

Posture matches `/portfolio/fds` exactly: `portfolio_identity`, reads degrade to
an empty list with a note when there is no database, writes answer **503
`no_database`**, and another user's id is a **404**, never a 403.

Changing the set discards today's saved AI overview, so the next visit writes
one from the adjusted figures instead of replaying a narrative about a loss the
reader has just said is not real.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.overview import _overview_key
from api.routes.portfolio import portfolio_identity
from db.models import HoldingExclusion
from portfolio.models import AssetType
from services import exclusions as service
from services import portfolio_cache
from services.snapshots import attributed_day, optional_session

router = APIRouter(prefix="/portfolio/exclusions", tags=["portfolio"])

NO_DATABASE_NOTE = "No database is configured, so excluded holdings cannot be stored."


def _no_database() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "no_database",
            "message": (
                "This deployment has no database configured, so a holding cannot "
                "be excluded."
            ),
        },
    )


class ExclusionCreate(BaseModel):
    """The holding to exclude, identified the way M1 identifies every row."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=255)
    asset_type: str = Field(min_length=1, max_length=32)
    name: Optional[str] = Field(default=None, max_length=300)

    @field_validator("source")
    @classmethod
    def _not_manual(cls, value: str) -> str:
        if value.strip() == service.MANUAL_SOURCE:
            raise ValueError("a manual deposit is deleted, not excluded")
        return value.strip()

    @field_validator("asset_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        return AssetType.coerce(value).value

    @field_validator("name")
    @classmethod
    def _trim(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip() or None


def _exclusion_json(row: HoldingExclusion) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "external_id": row.external_id,
        "asset_type": row.asset_type,
        "name": row.name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _forget_todays_overview(session: AsyncSession, user_id: str) -> None:
    day = attributed_day(datetime.now(timezone.utc))
    await portfolio_cache.discard(session, user_id, _overview_key(day))


@router.get("")
async def list_exclusions(
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """The caller's excluded holdings, oldest first."""
    if session is None:
        return {"exclusions": [], "note": NO_DATABASE_NOTE}
    rows = await service.list_exclusions(session, user_id)
    return {"exclusions": [_exclusion_json(r) for r in rows], "note": None}


@router.post("", status_code=201)
async def create_exclusion(
    body: ExclusionCreate,
    response: Response,
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> dict[str, Any]:
    """Exclude a holding. 201 when new, 200 with the existing row when not."""
    if session is None:
        raise _no_database()
    row, created = await service.exclude(
        session,
        user_id,
        source=body.source,
        external_id=body.external_id,
        asset_type=body.asset_type,
        name=body.name,
    )
    if created:
        await _forget_todays_overview(session, user_id)
    else:
        response.status_code = 200
    return _exclusion_json(row)


@router.delete("/{exclusion_id}", status_code=204)
async def delete_exclusion(
    exclusion_id: str,
    user_id: str = Depends(portfolio_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> None:
    """Put a holding back into the figures. 404 if it is not the caller's."""
    if session is None:
        raise _no_database()
    if not await service.restore(session, user_id, exclusion_id):
        raise HTTPException(status_code=404, detail="Unknown exclusion")
    await _forget_todays_overview(session, user_id)


__all__ = ["NO_DATABASE_NOTE", "ExclusionCreate", "router"]
