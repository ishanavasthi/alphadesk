"""Typed failures for the portfolio layer.

Every one of these exists because C2 found a way the naive code path fails
*silently* or with the wrong exception type:

- a throttled call arrives looking like a success, so indexing the payload
  raises ``KeyError`` instead of a retryable :class:`RateLimited`;
- the one asset type AlphaDesk exists for has a row shape nobody has ever seen,
  so a mapping mismatch must be a named error, not a ``KeyError`` three frames
  deep;
- no payload carries a currency, so a currency appearing at all is a broken
  assumption and must stop the caller rather than be summed.
"""

from __future__ import annotations

from typing import Any, Optional


class PortfolioSourceError(Exception):
    """Base class for every portfolio-source failure."""


class NotLinked(PortfolioSourceError):
    """No usable credential for this user at this source."""


class UserScopeError(PortfolioSourceError):
    """A connector was asked for a user it is not bound to.

    Until F3 every connector holds exactly one credential set. Serving a
    different ``user_id`` from it would be a cross-user data leak, so it is a
    hard error rather than a best effort.
    """


class PayloadShapeError(PortfolioSourceError):
    """The source returned something the documented shape does not cover."""


class UnverifiedShapeError(PayloadShapeError):
    """A payload behind an explicitly-unverified boundary deviated.

    Raised for ``IND_STOCK`` holdings rows, whose shape has never been observed
    populated (C2 §2.2). Mapping them is an educated guess, so any deviation is
    reported loudly instead of being coerced into a plausible-looking model.
    """


class SourceReportedError(PortfolioSourceError):
    """The payload carried an ``error`` body instead of data."""

    def __init__(self, tool: str, code: str, message: str = "") -> None:
        self.tool = tool
        self.code = code
        super().__init__(f"{tool}: source reported {code!r}{f': {message}' if message else ''}")


class RateLimited(SourceReportedError):
    """The source throttled the call.

    A **plain typed carrier**: it holds numbers a connector already read off a
    source's throttle body, and knows nothing about how any source encodes one.
    Parsing that body is the connector's job — an earlier version of this class
    did it here, which quietly put vendor key names above the connector
    boundary.

    Callers get the throttle facts in normalized form: which tier tripped, its
    limit, what this call cost, and how long the source asked us to wait. All of
    it is source-reported, never assumed — hard-coding one tier's limit means
    misreading the other tier as an outage.
    """

    def __init__(
        self,
        tool: str,
        code: str,
        *,
        message: str = "",
        scope: Optional[str] = None,
        window: Optional[str] = None,
        limit: Optional[float] = None,
        current: Optional[float] = None,
        cost: Optional[float] = None,
        retry_after: Optional[float] = None,
        body: Optional[dict] = None,
    ) -> None:
        self.scope = scope
        self.window = window
        self.limit = limit
        self.current = current
        self.cost = cost
        #: Seconds the source asked us to wait. Named for what it means, not
        #: for what any one vendor calls it.
        self.retry_after = retry_after
        self.body = body or {}
        super().__init__(tool, code, message)


class SourceUnavailable(PortfolioSourceError):
    """The call could not be completed — transport, network or server failure.

    Exists so that **everything** a connector can raise is catchable as
    :class:`PortfolioSourceError`. Without it a client-library exception escapes
    the abstraction raw, and a caller writing
    ``except PortfolioSourceError`` silently misses it.
    """


class NonInrValue(PortfolioSourceError):
    """A payload declared a currency, and it was not INR.

    v2's currency stance is an assumption the source gives us no field to check
    (C2 Q4). The moment a payload *does* carry one and disagrees, the assumption
    is falsified and every cross-asset total built on it is wrong — so this
    raises rather than degrading.
    """

    def __init__(self, tool: str, path: str, value: Any) -> None:
        self.tool = tool
        self.path = path
        self.value = value
        super().__init__(
            f"{tool}: payload declares a currency at {path!r} that is not INR "
            f"({value!r}). v2 assumes the source converts everything to INR; "
            "that assumption is now falsified — do not sum these values."
        )


class UnsupportedAssetType(PortfolioSourceError):
    """The source cannot be queried for this asset type."""


__all__ = [
    "NonInrValue",
    "NotLinked",
    "PayloadShapeError",
    "PortfolioSourceError",
    "RateLimited",
    "SourceReportedError",
    "SourceUnavailable",
    "UnsupportedAssetType",
    "UnverifiedShapeError",
    "UserScopeError",
]
