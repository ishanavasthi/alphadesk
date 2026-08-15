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

    Arrives as an ordinary, successful-looking response (MCP ``isError: false``)
    whose body *replaces* the payload. Two tiers exist (per-tool, then global)
    and calls are not equally priced, so every number below is read off the body
    rather than assumed — a client that hard-codes one tier's limit misreads the
    other as an outage.
    """

    def __init__(
        self,
        tool: str,
        *,
        message: str = "",
        scope: Optional[str] = None,
        window: Optional[str] = None,
        limit: Optional[float] = None,
        current: Optional[float] = None,
        cost: Optional[float] = None,
        retry_after_seconds: Optional[float] = None,
        body: Optional[dict] = None,
    ) -> None:
        self.scope = scope
        self.window = window
        self.limit = limit
        self.current = current
        self.cost = cost
        self.retry_after_seconds = retry_after_seconds
        self.body = body or {}
        super().__init__(tool, "rate_limit_exceeded", message)

    @classmethod
    def from_body(cls, tool: str, body: dict) -> "RateLimited":
        def num(key: str) -> Optional[float]:
            value: Any = body.get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        return cls(
            # The body names the tool that tripped; fall back to the caller's.
            body.get("tool") if isinstance(body.get("tool"), str) else tool,
            message=body.get("message") if isinstance(body.get("message"), str) else "",
            scope=body.get("scope") if isinstance(body.get("scope"), str) else None,
            window=body.get("window") if isinstance(body.get("window"), str) else None,
            limit=num("limit"),
            current=num("current"),
            cost=num("cost"),
            retry_after_seconds=num("retry_after_seconds"),
            body=body,
        )


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
    "UnsupportedAssetType",
    "UnverifiedShapeError",
    "UserScopeError",
]
