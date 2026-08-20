"""Manually entered fixed deposits: accrual math, CRUD, and the holdings bridge.

Card B10. A fixed deposit is the one holding on this dashboard whose value is
**computed rather than quoted** — principal, annual rate, compounding
convention and two dates are the entire instrument, and no price feed is
involved anywhere. That is why manual entry starts here: the user types the
terms once and the value tracks itself, instead of being a number that goes
stale the moment it is saved.

It also has to start here. IND Money's FD reporting is verified broken
(B9/#65 — a Rs 5,000 deposit reported at Rs 162, `total_pnl` frozen at exactly
-4,838 for five consecutive days, the FD bucket vanishing from `total_networth`
and then from the breakdown). These rows are **additive**: they sit alongside
whatever the vendor reports and never overwrite, reconcile against or repair
it. Presenting the vendor's FD bucket is B9's problem.

Three rules shape the module:

1. **`Decimal` everywhere, no float, ever.** Not one `float()` call, not one
   `math.pow`. `Decimal ** Decimal` handles the fractional exponent at context
   precision, and money is quantized to paise exactly once, at the end.
2. **Nothing is stored derived.** There is no `current_value` column: a saved
   valuation is wrong by the next morning. Every read recomputes — that *is*
   the tracking.
3. **The clamps are the honesty.** Before `start_date` the value is the
   principal (a deposit that has not started has earned nothing); after
   `maturity_date` the value freezes at the maturity value. A deposit does not
   keep compounding because nobody closed the browser tab.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ManualFd, utcnow
from portfolio.models import AssetType, Holding, derive_pnl
from services.snapshots import IST
from tools.ind_money_auth import ensure_user_row

#: The `source` every manual row carries. `(source, external_id)` is M1's
#: identity pair, so a manual FD can never collide with a vendor row no matter
#: what id the vendor invents — and the frontend branches on this one string to
#: say where a number came from.
SOURCE = "manual"

#: How many times a year interest is added to the principal. `simple` is not in
#: here because it is not a compounding frequency at all — it is the other
#: formula.
COMPOUNDING_PERIODS: dict[str, int] = {
    "monthly": 12,
    "quarterly": 4,
    "half_yearly": 2,
    "yearly": 1,
}

SIMPLE = "simple"

#: Everything the API accepts, in the order the frontend lists them.
COMPOUNDING_CHOICES: tuple[str, ...] = (
    "monthly",
    "quarterly",
    "half_yearly",
    "yearly",
    SIMPLE,
)

#: Indian bank FDs compound quarterly, so it is the right answer for most rows
#: and the only defensible default.
DEFAULT_COMPOUNDING = "quarterly"

#: Actual/365. Banks vary (365/366, and month-count conventions for partial
#: quarters); this is one convention applied consistently, documented as an
#: approximation, rather than a per-bank rulebook nobody can verify.
DAYS_PER_YEAR = Decimal(365)

#: Guard, not a business rule: a rate above this is a typo (7.25 entered as
#: 725), and catching it costs nothing.
MAX_RATE_PCT = Decimal(50)

_PAISE = Decimal("0.01")

#: Fields a client may write. The API mirrors this; the service refuses
#: anything else so a future route cannot quietly make `id` or `user_id`
#: editable.
EDITABLE_FIELDS = (
    "label",
    "principal",
    "rate_pct",
    "compounding",
    "start_date",
    "maturity_date",
)


def _money(value: Decimal) -> Decimal:
    """Quantize to paise, once, at the end of a calculation."""
    return value.quantize(_PAISE, rounding=ROUND_HALF_UP)


def today_ist(now: Optional[datetime] = None) -> date:
    """The IST calendar day to value a deposit on.

    Deliberately **not** `services.snapshots.attributed_day`: that helper
    attributes a run before 06:00 IST to the *previous* day, which is a rule
    about when the capture job runs and has nothing to do with what day a
    deposit has accrued to. It is the same IST zone, though — this codebase has
    exactly one, and a second definition of "today" is how two screens end up
    disagreeing about someone's money.
    """
    return (now or datetime.now(timezone.utc)).astimezone(IST).date()


# --------------------------------------------------------------------------- #
# The math — pure, Decimal-only, no session, no I/O
# --------------------------------------------------------------------------- #
def year_fraction(start_date: date, maturity_date: date, as_of: date) -> Decimal:
    """Years elapsed on the deposit at ``as_of``: actual/365, clamped both ends.

    ``max(0, (min(as_of, maturity_date) - start_date).days) / 365``. The lower
    clamp is a future-dated deposit (no accrual before it starts); the upper one
    is the whole point of the "frozen at maturity" rule — past the term this
    stops growing, so every downstream figure freezes with it.
    """
    end = min(as_of, maturity_date)
    days = (end - start_date).days
    if days <= 0:
        return Decimal(0)
    return Decimal(days) / DAYS_PER_YEAR


def value_at(
    principal: Decimal,
    rate_pct: Decimal,
    compounding: str,
    years: Decimal,
) -> Decimal:
    """The deposit's value after ``years``, under one compounding convention.

    Cumulative: ``principal * (1 + r/n) ** (n * years)``.
    Simple: ``principal * (1 + r * years)``.

    **The fractional exponent is a documented approximation.** A real bank adds
    interest on quarter boundaries and pays simple interest on the stub period
    after the last one; this compounds continuously *within* the period instead.
    The two agree exactly on period boundaries and differ by rupees, not
    percent, in between — the honest trade for a formula a user can check
    against their own bank statement.
    """
    rate = Decimal(rate_pct) / Decimal(100)
    if compounding == SIMPLE:
        return principal * (Decimal(1) + rate * years)
    periods = COMPOUNDING_PERIODS.get(compounding)
    if periods is None:
        raise ValueError(f"unknown compounding convention: {compounding!r}")
    n = Decimal(periods)
    # `Decimal ** Decimal` with a non-integer exponent, at context precision —
    # never `float(...) ** float(...)`, which is where the paise go missing.
    return principal * (Decimal(1) + rate / n) ** (n * years)


@dataclass(frozen=True)
class FdValuation:
    """What a deposit is worth today, and what it will be worth at maturity."""

    current_value: Decimal
    accrued_interest: Decimal
    maturity_value: Decimal
    matured: bool
    days_to_maturity: int


def valuation(
    principal: Decimal,
    rate_pct: Decimal,
    compounding: str,
    start_date: date,
    maturity_date: date,
    as_of: date,
) -> FdValuation:
    """The full picture for one deposit at ``as_of``.

    ``matured`` is ``as_of >= maturity_date``, and on a matured deposit
    ``current_value == maturity_value`` by construction — the year fraction is
    clamped, so there is no second code path that could drift from the first.

    ``days_to_maturity`` floors at 0 rather than going negative: a matured
    deposit is not "-31 days away", it has arrived, and `matured` is the flag
    that says so.
    """
    current = _money(
        value_at(principal, rate_pct, compounding, year_fraction(start_date, maturity_date, as_of))
    )
    at_maturity = _money(
        value_at(
            principal,
            rate_pct,
            compounding,
            year_fraction(start_date, maturity_date, maturity_date),
        )
    )
    return FdValuation(
        current_value=current,
        accrued_interest=current - principal,
        maturity_value=at_maturity,
        matured=as_of >= maturity_date,
        days_to_maturity=max(0, (maturity_date - as_of).days),
    )


def value_row(fd: ManualFd, as_of: date) -> FdValuation:
    """:func:`valuation` for a stored row. The only place the two are joined."""
    return valuation(
        Decimal(fd.principal),
        Decimal(fd.rate_pct),
        fd.compounding,
        fd.start_date,
        fd.maturity_date,
        as_of,
    )


# --------------------------------------------------------------------------- #
# CRUD — every function takes the user id, and scopes on it
# --------------------------------------------------------------------------- #
async def list_fds(session: AsyncSession, user_id: str) -> list[ManualFd]:
    """``user_id``'s deposits, soonest maturity first."""
    result = await session.execute(
        select(ManualFd)
        .where(ManualFd.user_id == user_id)
        .order_by(ManualFd.maturity_date, ManualFd.created_at)
    )
    return list(result.scalars().all())


async def get_fd(session: AsyncSession, user_id: str, fd_id: str) -> Optional[ManualFd]:
    """One deposit **of this user's**, or None.

    Scoped on `user_id` in the query itself, not checked afterwards: another
    user's id has to be indistinguishable from an id that does not exist, and
    the surest way to guarantee that is never to load the row.
    """
    result = await session.execute(
        select(ManualFd).where(ManualFd.user_id == user_id, ManualFd.id == fd_id)
    )
    return result.scalars().first()


async def create_fd(
    session: AsyncSession,
    user_id: str,
    *,
    label: str,
    principal: Decimal,
    rate_pct: Decimal,
    compounding: str,
    start_date: date,
    maturity_date: date,
) -> ManualFd:
    """Insert one deposit for ``user_id``.

    The FK onto `users` must resolve first — a JWT caller was inserted by
    `register_identity`, but a single-tenant `"local"` operator may have no row
    yet. Same guard the watchlist writes use (`api.main._persist_watchlist`).
    """
    await ensure_user_row(session, user_id)
    fd = ManualFd(
        user_id=user_id,
        label=label,
        principal=principal,
        rate_pct=rate_pct,
        compounding=compounding,
        start_date=start_date,
        maturity_date=maturity_date,
    )
    session.add(fd)
    await session.commit()
    await session.refresh(fd)
    return fd


async def update_fd(
    session: AsyncSession,
    user_id: str,
    fd_id: str,
    changes: dict[str, Any],
) -> Optional[ManualFd]:
    """Apply a partial edit, returning the updated row (or None if not theirs).

    Every field is editable — a mistyped rate or date is the most likely reason
    anybody opens this dialog — but `id`, `user_id` and the timestamps are not
    fields, so :data:`EDITABLE_FIELDS` is enforced here rather than trusted from
    the caller.
    """
    fd = await get_fd(session, user_id, fd_id)
    if fd is None:
        return None
    for field, value in changes.items():
        if field not in EDITABLE_FIELDS:
            raise ValueError(f"{field!r} is not editable")
        setattr(fd, field, value)
    fd.updated_at = utcnow()
    session.add(fd)
    await session.commit()
    await session.refresh(fd)
    return fd


async def delete_fd(session: AsyncSession, user_id: str, fd_id: str) -> bool:
    """Drop one of ``user_id``'s deposits; True if a row went."""
    result = await session.execute(
        sa_delete(ManualFd).where(ManualFd.user_id == user_id, ManualFd.id == fd_id)
    )
    await session.commit()
    return bool(result.rowcount or 0)


# --------------------------------------------------------------------------- #
# The bridge into the portfolio model
# --------------------------------------------------------------------------- #
async def as_holdings(
    session: AsyncSession,
    user_id: str,
    as_of: Optional[datetime] = None,
) -> list[Holding]:
    """``user_id``'s deposits as M1 `Holding` rows, valued now.

    `source="manual"` is what makes these safe to append to a vendor list: M1's
    identity is `(source, external_id)`, so a manual row can never be mistaken
    for — or collide with — anything IND Money returned, and the frontend can
    label provenance from the same field.

    P&L goes through `derive_pnl`, never inline arithmetic: the cost basis rules
    (`invested_amount == 0` means *unknown*, and an unknown basis yields no P&L
    at all) live in exactly one function, and a second copy here is how they
    drift apart.
    """
    stamped = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    day = today_ist(stamped)
    rows: list[Holding] = []
    for fd in await list_fds(session, user_id):
        computed = value_row(fd, day)
        principal = Decimal(fd.principal)
        pnl, pnl_pct = derive_pnl(computed.current_value, principal)
        rows.append(
            Holding(
                source=SOURCE,
                external_id=fd.id,
                asset_type=AssetType.FD,
                name=fd.label,
                invested_amount=principal,
                current_value=computed.current_value,
                pnl=pnl,
                pnl_pct=pnl_pct,
                as_of=stamped,
            )
        )
    return rows


async def manual_total(
    session: AsyncSession,
    user_id: str,
    as_of: Optional[datetime] = None,
) -> tuple[Decimal, int]:
    """``(sum of accrued values, count)`` for the `/portfolio/summary` block.

    Summed from the same valuation the list and the holdings merge use, so the
    three can never disagree — the alternative, a SQL `SUM(principal)`, would
    report a different number on the same screen.

    No deposits returns an unquantized `Decimal(0)`, which serializes as ``"0"``
    — the same literal the no-database path returns, so a client never has to
    tell ``"0"`` and ``"0.00"`` apart to decide the block is empty.
    """
    day = today_ist(as_of)
    total = Decimal(0)
    count = 0
    for fd in await list_fds(session, user_id):
        total += value_row(fd, day).current_value
        count += 1
    return (_money(total) if count else total), count


__all__ = [
    "COMPOUNDING_CHOICES",
    "COMPOUNDING_PERIODS",
    "DEFAULT_COMPOUNDING",
    "EDITABLE_FIELDS",
    "MAX_RATE_PCT",
    "SIMPLE",
    "SOURCE",
    "FdValuation",
    "as_holdings",
    "create_fd",
    "delete_fd",
    "get_fd",
    "list_fds",
    "manual_total",
    "today_ist",
    "update_fd",
    "valuation",
    "value_at",
    "value_row",
    "year_fraction",
]
