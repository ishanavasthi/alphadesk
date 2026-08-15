"""Source-neutral portfolio model (card M1).

Every type here is deliberately *not* shaped like any vendor payload. The whole
point of the module is that `backend/portfolio/connectors/` is the only place
that knows what IND Money (or any future source) calls its fields; everything
above this boundary speaks the vocabulary below.

Four rules are baked into the types themselves rather than left to callers,
because C2 (`docs/ind_money_payloads.md`) proved each one is a real failure mode:

1. **`Decimal` for every money/percent value.** The source emits `int` for an
   integral value and `float` otherwise — for the same field, on different rows.
   Coercion always goes through `str`, never through binary float.
2. **Unknown cost basis is `None`, not `0`.** The vendor documents that linked
   brokers return `invested_amount` as `0` when it is missing. A `0` fed into
   P&L fabricates a 100% gain, so `Holding` refuses to hold `invested_amount ==
   0` at all, and refuses to carry a P&L when the cost basis is unknown.
3. **No date comes from any payload.** `as_of` is stamped by the connector at
   fetch time and must be timezone-aware.
4. **One currency.** No payload carries a currency field anywhere, and the
   vendor sums US holdings into its own INR totals, so v2 declares `INR` and
   the connectors raise if a payload ever contradicts that. The US-exposure
   signal is the asset type, not a currency tag — see :func:`is_us_exposure`.

There is deliberately **no XIRR** in this module. C2 found the vendor's own
field dead (0 in 14 of 14 rows) and no dated cashflow anywhere in the API to
compute one from. The return metric is `pnl` / `pnl_pct`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Any, Iterable, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

#: The only currency v2 models. See rule 4 above and `docs/SPECS/M1.md`.
CURRENCY = "INR"

#: Asset-type strings that mean "denominated abroad, converted by the source".
#: Membership here is the *only* US-exposure signal that exists — there is no
#: currency field to read.
US_EXPOSURE_TYPES = frozenset({"US_STOCK", "US_STOCK_WALLET"})


class AssetType(str, Enum):
    """The 16 asset types the source can be queried for, plus a sentinel.

    ``UNKNOWN`` is not a vendor value. It is where any asset-type string that is
    not one of the 16 lands — the snapshot really does report a bucket
    (``US_STOCK_WALLET``) that the holdings endpoint's enum does not accept, so
    an unknown string is a normal Tuesday, not a bug. The original string is
    always preserved alongside, in ``asset_type_raw``.
    """

    IND_STOCK = "IND_STOCK"
    MF = "MF"
    US_STOCK = "US_STOCK"
    BOND = "BOND"
    EPF = "EPF"
    NPS = "NPS"
    SA = "SA"
    FD = "FD"
    CRYPTO = "CRYPTO"
    INSURANCE = "INSURANCE"
    VEHICLE = "VEHICLE"
    RE = "RE"
    RD = "RD"
    AIF = "AIF"
    PMS = "PMS"
    PPF = "PPF"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def queryable(cls) -> tuple["AssetType", ...]:
        """The 16 types a source will accept as a query argument."""
        return tuple(m for m in cls if m is not cls.UNKNOWN)

    @classmethod
    def coerce(cls, value: Any) -> "AssetType":
        """Map any source string onto the enum, never raising."""
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            return cls.UNKNOWN
        try:
            return cls(value.strip().upper())
        except ValueError:
            return cls.UNKNOWN


class BreakdownBy(str, Enum):
    """The three slices an allocation can be requested in."""

    ASSETS = "assets"
    SECTOR = "sector"
    MARKET_CAP = "market_cap"


class LinkHealth(str, Enum):
    """How usable this user's link to the source is, right now.

    - ``LINKED`` — a usable credential exists.
    - ``EXPIRING`` — usable, but inside the expiry threshold and not yet renewed.
      A connector must **not** report ``LINKED`` merely because it holds a
      refresh token: a future source may be authorization-code-only, with no
      refresh at all.
    - ``NEEDS_RELINK`` — no usable credential; the user must authorize again.
    - ``REVOKED`` — the source explicitly rejected our credential. Strictly
      stronger than ``NEEDS_RELINK``: the grant is dead at the source, not just
      missing here.
    """

    LINKED = "linked"
    EXPIRING = "expiring"
    NEEDS_RELINK = "needs_relink"
    REVOKED = "revoked"


class SipKind(str, Enum):
    MF = "mf"
    IND_STOCK = "ind_stock"


# --------------------------------------------------------------------------- #
# Coercion helpers
# --------------------------------------------------------------------------- #
def to_decimal(value: Any) -> Optional[Decimal]:
    """Coerce a source number to ``Decimal`` via ``str``, or ``None``.

    ``Decimal(0.1)`` is not ``0.1``; ``Decimal(str(0.1))`` is. Since the source
    mixes `int` and `float` for the same field, everything takes the same route.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError(f"expected a number, got a bool: {value!r}")
    if isinstance(value, (int, float, str)):
        text = str(value).strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"not a number: {value!r}") from exc
    raise ValueError(f"not a number: {value!r}")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "as_of must be timezone-aware — no payload carries a date, so the "
            "connector stamps fetch time and an ambiguous local time is a bug"
        )
    return value.astimezone(timezone.utc)


def _inr_only(value: str) -> str:
    text = (value or "").strip().upper()
    if text != CURRENCY:
        raise ValueError(
            f"v2 models {CURRENCY} only; got {value!r}. No payload carries a "
            "currency field, so a non-INR value means an assumption broke — "
            "raise rather than silently summing it into an INR total."
        )
    return text


Money = Annotated[Decimal, BeforeValidator(to_decimal)]
MoneyOpt = Annotated[Optional[Decimal], BeforeValidator(to_decimal)]
Timestamp = Annotated[datetime, AfterValidator(_aware_utc)]
CurrencyCode = Annotated[str, AfterValidator(_inr_only)]


def derive_pnl(
    current_value: Optional[Decimal],
    invested_amount: Optional[Decimal],
) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """P&L and P&L% from a cost basis, or ``(None, None)`` when it is unknown.

    Never computes from a missing or zero cost basis — that is the fabricated
    ±100% this card exists to prevent.
    """
    if current_value is None or invested_amount is None or invested_amount == 0:
        return None, None
    pnl = current_value - invested_amount
    pct = (pnl / invested_amount * Decimal(100)).quantize(Decimal("0.01"))
    return pnl, pct


def stable_external_id(*parts: Any) -> str:
    """A deterministic id for a row whose source id is missing or empty.

    Weaker than a real instrument id: it is stable only for as long as the
    fields it hashes are. Connectors use it as a fallback, never as the primary.
    """
    # JSON-encoded, not string-joined: any separator character can also occur
    # inside a field, and ("a|b",) must not collide with ("a", "b").
    payload = json.dumps([None if p is None else str(p) for p in parts])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def is_us_exposure(asset_type: AssetType, asset_type_raw: Optional[str] = None) -> bool:
    """Whether a row is foreign-denominated at the source.

    The source converts to INR itself and publishes no currency field, so this
    is a *display* signal (badge it), not a conversion instruction.
    """
    if asset_type is not AssetType.UNKNOWN:
        return asset_type.value in US_EXPOSURE_TYPES
    return (asset_type_raw or "").strip().upper() in US_EXPOSURE_TYPES


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PnlBearing(_Model):
    """Shared invariant: no P&L without a known cost basis."""

    @model_validator(mode="after")
    def _no_pnl_without_cost_basis(self) -> "_PnlBearing":
        invested = getattr(self, "invested_amount", None)
        if invested == 0:
            raise ValueError(
                "invested_amount == 0 means UNKNOWN cost basis at the source, "
                "not 'invested nothing' — connectors must map it to None"
            )
        if invested is None and (self.pnl is not None or self.pnl_pct is not None):
            raise ValueError(
                "cost basis is unknown, so P&L cannot be known either; a "
                "pass-through 0 from the source is meaningless on such a row"
            )
        return self


class Holding(_PnlBearing):
    """One position, normalized.

    Identity is ``(source, external_id)``. ``current_value`` is the only always-
    required number: it is the one figure every source row carries.
    """

    source: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    asset_type: AssetType
    #: The source's own asset-type string, kept verbatim — the only way to tell
    #: two different UNKNOWN buckets apart.
    asset_type_raw: Optional[str] = None
    symbol: Optional[str] = None
    #: Human-readable label. Not guaranteed: the source returns an empty string
    #: on some rows, which normalizes to None here.
    name: Optional[str] = None
    isin: Optional[str] = None
    units: MoneyOpt = None
    avg_cost: MoneyOpt = None
    invested_amount: MoneyOpt = None
    current_price: MoneyOpt = None
    current_value: Money
    pnl: MoneyOpt = None
    pnl_pct: MoneyOpt = None
    currency: CurrencyCode = CURRENCY
    as_of: Timestamp
    raw: dict = Field(default_factory=dict)

    @property
    def is_us_exposure(self) -> bool:
        return is_us_exposure(self.asset_type, self.asset_type_raw)


class AllocationSlice(_PnlBearing):
    """One bucket of an aggregate: an asset type, asset class, sector or cap band.

    ``asset_type`` is set only on asset-type slices; the other three kinds carry
    a free-form ``label`` the source does not enumerate — never hardcode against
    those strings.
    """

    label: str
    asset_type: Optional[AssetType] = None
    asset_type_raw: Optional[str] = None
    invested_amount: MoneyOpt = None
    current_value: Money
    pnl: MoneyOpt = None
    pnl_pct: MoneyOpt = None
    #: The bucket's share of the portfolio, as the source reports it.
    weight_pct: MoneyOpt = None
    currency: CurrencyCode = CURRENCY
    raw: dict = Field(default_factory=dict)


class Allocation(_Model):
    """The result of one ``(asset_type, by)`` allocation request.

    One request, one object. Sweeping the full grid is explicitly forbidden —
    see the rate-limit policy in `docs/SPECS/M1.md`.
    """

    source: str = Field(min_length=1)
    asset_type: AssetType
    by: BreakdownBy
    as_of: Timestamp
    currency: CurrencyCode = CURRENCY
    slices: list[AllocationSlice] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class PortfolioSnapshot(_Model):
    """Whole-portfolio aggregate, as the source reports it.

    **Nothing here is recomputed from holdings, and nothing may assert that it
    reconciles with them.** C2 measured the gap: the source reports a bucket the
    holdings endpoint cannot enumerate at all (~2.3% of the total), and even
    adding it back leaves per-type residuals up to ~0.94%. The totals below are
    the source's own numbers, passed straight through.
    """

    source: str = Field(min_length=1)
    as_of: Timestamp
    currency: CurrencyCode = CURRENCY
    #: Net of liabilities — the source's headline figure.
    net_worth: Money
    #: Gross portfolio value, before liabilities.
    gross_value: MoneyOpt = None
    invested_total: MoneyOpt = None
    liabilities_total: MoneyOpt = None
    by_asset_type: list[AllocationSlice] = Field(default_factory=list)
    by_asset_class: list[AllocationSlice] = Field(default_factory=list)
    by_sector: list[AllocationSlice] = Field(default_factory=list)
    by_market_cap: list[AllocationSlice] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)

    def us_exposure_slices(self) -> list[AllocationSlice]:
        """Asset-type buckets that are foreign-denominated at the source."""
        return [
            s
            for s in self.by_asset_type
            if s.asset_type is not None and is_us_exposure(s.asset_type, s.asset_type_raw)
        ]


class Sip(_Model):
    """A scheduled recurring investment.

    ⚠️ **UNVERIFIED row shape.** Both SIP endpoints returned zero rows in C2, so
    no populated row has ever been observed. Connectors map defensively and
    leave unmapped material in ``raw``.
    """

    source: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    kind: SipKind
    name: Optional[str] = None
    amount: MoneyOpt = None
    frequency: Optional[str] = None
    #: Forward-looking. The source has no past-dated cashflow anywhere, which is
    #: why no money-weighted return is derivable from it.
    next_execution_at: Optional[Timestamp] = None
    status: Optional[str] = None
    as_of: Timestamp
    currency: CurrencyCode = CURRENCY
    raw: dict = Field(default_factory=dict)


def sum_holdings_value(holdings: Iterable[Holding]) -> Decimal:
    """Sum of holding values. A sum of rows — *not* a net-worth figure.

    Kept separate from :attr:`PortfolioSnapshot.net_worth` on purpose: the two
    do not, and cannot, agree.
    """
    return sum((h.current_value for h in holdings), Decimal(0))


__all__ = [
    "CURRENCY",
    "US_EXPOSURE_TYPES",
    "Allocation",
    "AllocationSlice",
    "AssetType",
    "BreakdownBy",
    "Holding",
    "LinkHealth",
    "PortfolioSnapshot",
    "Sip",
    "SipKind",
    "derive_pnl",
    "is_us_exposure",
    "stable_external_id",
    "to_decimal",
    "sum_holdings_value",
]
