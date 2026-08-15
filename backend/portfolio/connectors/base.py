"""The connector seam: one interface, two real implementations.

Everything above this line speaks `portfolio.models`. Everything below it knows
a specific vendor's field names. That is the whole contract — if a vendor key
name shows up outside `portfolio/connectors/`, the seam has leaked (there is a
test that greps for exactly that).

Every method takes an explicit ``user_id``. It is the constant ``"local"`` at
call sites until F3 introduces real accounts, but it is never implicit and never
a module global: retrofitting a user argument into a shipped data path is how
cross-user leaks get written.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from portfolio.models import (
    Allocation,
    AssetType,
    BreakdownBy,
    Holding,
    LinkHealth,
    PortfolioSnapshot,
    Sip,
)

#: The single user every call site passes until F3 lands real accounts.
LOCAL_USER_ID = "local"


class PortfolioConnector(ABC):
    """A read-only portfolio source.

    Implementations are interchangeable: one shared contract-test suite runs
    against every one of them (`backend/tests/test_portfolio_connector_contract.py`).
    """

    #: Value written to ``Holding.source``; half of the ``(source, external_id)``
    #: identity pair.
    source: ClassVar[str]

    @abstractmethod
    async def fetch_snapshot(self, user_id: str) -> PortfolioSnapshot:
        """Whole-portfolio aggregate, as the source reports it.

        Totals are passed through, never recomputed from holdings, and callers
        must not assert that they reconcile with a holdings sum — they do not.
        """

    @abstractmethod
    async def fetch_holdings(self, user_id: str, asset_type: AssetType) -> list[Holding]:
        """Rows for one asset type.

        An asset type the user holds nothing in returns ``[]`` — that is a valid
        answer, not an error. ``AssetType.UNKNOWN`` is only queryable on sources
        that can enumerate their own non-standard buckets; the rest raise
        :class:`portfolio.errors.UnsupportedAssetType`.
        """

    @abstractmethod
    async def fetch_allocation(
        self, user_id: str, asset_type: AssetType, by: BreakdownBy
    ) -> Allocation:
        """One ``(asset_type, by)`` slice, fetched lazily.

        Deliberately singular. Sources rate-limit per tool and price calls
        unequally, so sweeping the whole grid up front is forbidden; ask for the
        slice the caller actually wants.
        """

    @abstractmethod
    async def fetch_sips(self, user_id: str) -> list[Sip]:
        """Scheduled recurring investments. Forward-looking only."""

    @abstractmethod
    async def link_health(self, user_id: str) -> LinkHealth:
        """How usable this user's link is right now.

        Must be answered from the credential's *observed* state. Holding a
        refresh token is not evidence of health — a source may not support
        refresh at all, in which case only re-authorization restores the link.
        """


__all__ = ["LOCAL_USER_ID", "PortfolioConnector"]
