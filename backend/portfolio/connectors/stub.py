"""Stub connector — a second real source, not test scaffolding.

It exists for three reasons that outlive M1:

1. It proves the connector interface has **two implementations**, i.e. that the
   seam is a seam and not a rename of the IND Money client.
2. It backs the public `/demo` route (card U1), so a visitor with no linked
   broker still sees a full dashboard.
3. It makes F4's cross-user isolation testable in CI forever, with no network,
   no credential and no live account.

Its data is 100% invented and lives in `backend/tests/fixtures/demo/` — see that
directory's README for the edge cases the portfolio deliberately contains
(unknown cost basis, a zero-value row, an UNKNOWN asset type, and a snapshot
bucket with no holdings rows so the totals deliberately do not reconcile).

The fixtures are written in the **model's** vocabulary, not a vendor's. Derived
numbers are computed here through the same helpers the IND Money connector uses,
so the degrade rules are genuinely exercised rather than pre-baked into JSON.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

from portfolio.errors import PayloadShapeError, UserScopeError
from portfolio.models import (
    Allocation,
    AllocationSlice,
    AssetType,
    BreakdownBy,
    Holding,
    LinkHealth,
    PortfolioSnapshot,
    Sip,
    SipKind,
    derive_pnl,
    to_decimal,
)

from .base import PortfolioConnector

SOURCE = "stub"

#: Default demo portfolio. Product code reading from `tests/` is deliberate:
#: card M1 owns this directory and the same invented portfolio is what the
#: contract tests and the public demo route must agree about.
DEMO_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load(directory: Path, name: str) -> Any:
    """Read a demo file. Deliberately uncached — a shared mutable dict handed
    out as ``raw`` on every call is a bug waiting to be written."""
    path = directory / name
    if not path.is_file():
        raise PayloadShapeError(f"demo fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _decimal_at(path: str, value: Any) -> Optional[Decimal]:
    """`to_decimal` with a typed failure, so a malformed demo file degrades the
    same way a malformed vendor payload does."""
    try:
        return to_decimal(value)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise PayloadShapeError(f"demo fixture: {path} is not a usable number") from exc


def _required_id(path: str, row: Any) -> str:
    """The row's identity, or a typed error naming where it was missing.

    A bare ``KeyError`` here would escape the `PortfolioSourceError` hierarchy,
    which is the one promise every caller of this interface is allowed to rely
    on. The stub is a real source; it fails like one.
    """
    if not isinstance(row, dict):
        raise PayloadShapeError(f"demo fixture: {path} is not an object")
    value = row.get("external_id")
    if value is None or str(value).strip() == "":
        raise PayloadShapeError(f"demo fixture: {path} has no external_id")
    return str(value)


class StubConnector(PortfolioConnector):
    """Serves an invented portfolio, with no network and no credential.

    ``portfolios`` maps a ``user_id`` to its own fixture directory; anyone not
    listed gets ``default_dir``. That is what lets an isolation test hand two
    users two genuinely different portfolios and prove neither can see the
    other's.
    """

    source: ClassVar[str] = SOURCE

    def __init__(
        self,
        *,
        default_dir: Path = DEMO_FIXTURES,
        portfolios: Optional[dict[str, Path]] = None,
        clock: Callable[[], datetime] = _now_utc,
        health: LinkHealth = LinkHealth.LINKED,
    ) -> None:
        self._default_dir = Path(default_dir)
        self._portfolios = dict(portfolios or {})
        self._clock = clock
        self._health = health

    def _dir_for(self, user_id: str) -> Path:
        if not user_id:
            raise UserScopeError("user_id is required on every portfolio call")
        return self._portfolios.get(user_id, self._default_dir)

    # -------------------------------------------------------------- interface
    async def fetch_snapshot(self, user_id: str) -> PortfolioSnapshot:
        doc = _load(self._dir_for(user_id), "snapshot.json")
        net_worth = _decimal_at("snapshot.net_worth", doc.get("net_worth"))
        if net_worth is None:
            raise PayloadShapeError("demo snapshot has no net_worth")
        return PortfolioSnapshot(
            source=self.source,
            as_of=self._clock(),
            net_worth=net_worth,
            gross_value=_decimal_at("snapshot.gross_value", doc.get("gross_value")),
            invested_total=_decimal_at("snapshot.invested_total", doc.get("invested_total")),
            liabilities_total=_decimal_at(
                "snapshot.liabilities_total", doc.get("liabilities_total")
            ),
            by_asset_type=_slices(doc.get("by_asset_type")),
            by_asset_class=_slices(doc.get("by_asset_class")),
            by_sector=_slices(doc.get("by_sector")),
            by_market_cap=_slices(doc.get("by_market_cap")),
            raw=doc,
        )

    async def fetch_holdings(self, user_id: str, asset_type: AssetType) -> list[Holding]:
        buckets = _load(self._dir_for(user_id), "holdings.json")
        as_of = self._clock()
        holdings: list[Holding] = []
        for raw_type, bucket in buckets.items():
            # UNKNOWN collects every bucket whose label is outside the enum —
            # the stub can enumerate those, which the real source cannot.
            matches = (
                AssetType.coerce(raw_type) is AssetType.UNKNOWN
                if asset_type is AssetType.UNKNOWN
                else raw_type == asset_type.value
            )
            if matches:
                holdings.extend(
                    self._holding(row, index, raw_type, as_of)
                    for index, row in enumerate(bucket or [])
                )
        return holdings

    async def fetch_allocation(
        self, user_id: str, asset_type: AssetType, by: BreakdownBy
    ) -> Allocation:
        doc = _load(self._dir_for(user_id), "allocations.json")
        key = f"{asset_type.value}|{by.value}"
        # A combination with no rows is a valid answer, not an error — most of
        # the real grid is empty too.
        return Allocation(
            source=self.source,
            asset_type=asset_type,
            by=by,
            as_of=self._clock(),
            slices=_slices(doc.get(key)),
            raw={"key": key, "rows": doc.get(key) or []},
        )

    async def fetch_sips(self, user_id: str) -> list[Sip]:
        doc = _load(self._dir_for(user_id), "sips.json")
        as_of = self._clock()
        sips: list[Sip] = []
        for kind in (SipKind.MF, SipKind.IND_STOCK):
            for index, row in enumerate(doc.get(kind.value) or []):
                at = f"sips.{kind.value}[{index}]"
                sips.append(
                    Sip(
                        source=self.source,
                        external_id=_required_id(at, row),
                        kind=kind,
                        name=row.get("name"),
                        amount=_decimal_at(f"{at}.amount", row.get("amount")),
                        frequency=row.get("frequency"),
                        next_execution_at=_parse(
                            f"{at}.next_execution_at", row.get("next_execution_at")
                        ),
                        status=row.get("status"),
                        as_of=as_of,
                        raw=row,
                    )
                )
        return sips

    async def link_health(self, user_id: str) -> LinkHealth:
        self._dir_for(user_id)  # validates user_id
        # The stub needs no credential, so it is linked by construction. The
        # value is injectable so isolation tests can rehearse the other states.
        return self._health

    # ---------------------------------------------------------------- mapping
    def _holding(self, row: Any, index: int, asset_type_key: str, as_of: datetime) -> Holding:
        at = f"holdings.{asset_type_key}[{index}]"
        external_id = _required_id(at, row)
        current_value = _decimal_at(f"{at}.current_value", row.get("current_value"))
        if current_value is None:
            raise PayloadShapeError(f"demo fixture: {at} has no value")

        invested = _decimal_at(f"{at}.invested_amount", row.get("invested_amount"))
        if invested == 0:
            invested = None  # same rule as any source: 0 means unknown

        units = _decimal_at(f"{at}.units", row.get("units"))
        pnl, pnl_pct = derive_pnl(current_value, invested)
        avg_cost = (
            (invested / units).quantize(Decimal("0.0001"))
            if invested is not None and units not in (None, 0)
            else None
        )

        raw_type = str(row.get("asset_type") or "")
        return Holding(
            source=self.source,
            external_id=external_id,
            asset_type=AssetType.coerce(raw_type),
            asset_type_raw=raw_type or None,
            symbol=row.get("symbol"),
            name=row.get("name"),
            isin=row.get("isin"),
            units=units,
            avg_cost=avg_cost,
            invested_amount=invested,
            current_price=_decimal_at(f"{at}.current_price", row.get("current_price")),
            current_value=current_value,
            pnl=pnl,
            pnl_pct=pnl_pct,
            as_of=as_of,
            raw=row,
        )


def _slices(rows: Any) -> list[AllocationSlice]:
    out: list[AllocationSlice] = []
    for row in rows or []:
        at = f"allocation.{row.get('label')}"
        current_value = _decimal_at(f"{at}.current_value", row.get("current_value"))
        if current_value is None:
            raise PayloadShapeError(f"demo allocation row {row.get('label')!r} has no value")
        invested = _decimal_at(f"{at}.invested_amount", row.get("invested_amount"))
        if invested == 0:
            invested = None
        pnl, pnl_pct = derive_pnl(current_value, invested)
        raw_type = row.get("asset_type")
        out.append(
            AllocationSlice(
                label=str(row.get("label") or ""),
                asset_type=AssetType.coerce(raw_type) if raw_type else None,
                asset_type_raw=str(raw_type) if raw_type else None,
                invested_amount=invested,
                current_value=current_value,
                pnl=pnl,
                pnl_pct=pnl_pct,
                weight_pct=_decimal_at(f"{at}.weight_pct", row.get("weight_pct")),
                raw=row,
            )
        )
    return out


def _parse(path: str, value: Any) -> Optional[datetime]:
    """Parse a demo timestamp, or fail typed.

    A malformed date is a broken fixture, not a missing value, so it raises
    rather than degrading to ``None`` — but it raises inside the
    `PortfolioSourceError` hierarchy, because a bare `ValueError` out of a
    connector is exactly the untyped escape this card is meant to have none of.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise PayloadShapeError(f"demo fixture: {path} is not a usable timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = ["DEMO_FIXTURES", "SOURCE", "StubConnector"]
