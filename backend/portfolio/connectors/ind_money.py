"""IND Money connector — the only file that knows IND Money's field names.

Everything in here is driven by `docs/ind_money_payloads.md` (card C2), which is
the verified authority on what this server actually returns. The five facts that
shape the code:

1. Every response is ``{"result": "<stringified JSON>"}``; ``_unwrap`` in
   `tools/ind_money.py` already handles that, and this connector calls through
   it rather than re-implementing the transport.
2. **A throttled call looks like a success.** MCP ``isError`` is ``false`` and an
   ``error`` body *replaces* the payload, so ``payload["holdings"]`` would raise
   ``KeyError``. Every call therefore checks for ``error`` before touching data.
3. ``networth_holdings`` returns **two structurally different payloads**: a
   14-key aggregator row for MF/SA/FD/US_STOCK, and a 19-key live-trading
   envelope for ``IND_STOCK`` whose row shape **has never been observed
   populated**. That boundary is mapped strictly and fails loudly.
4. ``invested_amount`` of ``0`` means *unknown cost basis* (the vendor documents
   it for linked brokers), and cash-like rows carry ``total_units`` and
   ``unit_price`` of ``0`` beside a real value — so value is never derived from
   units × price, and neither is P&L derived from a zero cost basis.
5. There is **no date and no currency field anywhere**. ``as_of`` is stamped
   here; ``INR`` is declared here; if a currency ever appears and disagrees,
   the connector raises.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, ClassVar, Optional

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
    stable_external_id,
    to_decimal,
)

from .base import LOCAL_USER_ID, PortfolioConnector

Transport = Callable[[str, Optional[dict]], Awaitable[Any]]

SOURCE = "ind_money"

# --------------------------------------------------------------------------- #
# Vendor vocabulary — nothing below this comment may appear outside connectors/
# --------------------------------------------------------------------------- #
_TOOL_SNAPSHOT = "networth_snapshot"
_TOOL_HOLDINGS = "networth_holdings"
_TOOL_BREAKDOWN = "networth_allocation_breakdown"
_TOOL_MF_SIPS = "mf_sips"
_TOOL_STOCK_SIPS = "indian_stocks_sips"

#: The 14 keys every observed aggregator row carries, with no variation.
_ROW_KEYS = frozenset(
    {
        "asset_type",
        "assetclass_l2",
        "market_cap",
        "investment",
        "investment_code",
        "broker",
        "invested_amount",
        "market_value",
        "total_units",
        "unit_price",
        "total_pnl",
        "pnl_per",
        "holding_percent",
        "xirr",
    }
)

#: What a row must carry to count as "matches the documented shape", used only
#: behind the UNVERIFIED IND_STOCK boundary. `invested_amount` is deliberately
#: excluded: it is legitimately missing on real rows.
_ROW_STRICT_KEYS = _ROW_KEYS - {"invested_amount"}

#: Envelope-level flags meaning the broker-side fetch failed. An empty
#: `holdings` array alongside one of these is a FAILURE, not an empty portfolio.
_FETCH_ERROR_FLAGS = ("holding_error", "position_error")

#: The body of a throttled response, which arrives in place of the payload.
_RATE_LIMIT_CODE = "rate_limit_exceeded"
_RL_MESSAGE = "message"
_RL_SCOPE = "scope"
_RL_WINDOW = "window"
_RL_TOOL = "tool"
_RL_LIMIT = "limit"
_RL_CURRENT = "current"
_RL_COST = "cost"
_RL_RETRY_AFTER = "retry_after_seconds"

#: Discriminator key per breakdown slice.
_BREAKDOWN_LABEL_KEY = {
    BreakdownBy.ASSETS: "assetclass_l2",
    BreakdownBy.SECTOR: "sector",
    BreakdownBy.MARKET_CAP: "market_cap",
}

#: Where the snapshot keeps each aggregate, and which key labels its rows.
_SNAPSHOT_SECTIONS = (
    ("by_asset_type", "investments", "asset_type"),
    ("by_asset_class", "assets", "assetclass_l2"),
    ("by_sector", "sector", "sector"),
    ("by_market_cap", "market_cap", "market_cap"),
)

_SIP_ROWS_KEY = {SipKind.MF: "mf_sips", SipKind.IND_STOCK: "indian_stocks_sips"}
_SIP_TOOL = {SipKind.MF: _TOOL_MF_SIPS, SipKind.IND_STOCK: _TOOL_STOCK_SIPS}

# Unverified SIP row shape (both endpoints returned zero rows), so read by alias.
_SIP_NAME_KEYS = ("fund_name", "stock_name", "name", "investment", "scheme_name")
_SIP_AMOUNT_KEYS = ("sip_amount", "amount", "installment_amount")
_SIP_FREQUENCY_KEYS = ("frequency", "sip_frequency")
_SIP_STATUS_KEYS = ("status", "sip_status")
_SIP_NEXT_KEYS = ("next_execution_date", "next_installment_date", "next_date")
_SIP_ID_KEYS = ("sip_id", "id", "fund_id", "investment_code", "ind_key")

#: Floor for a retry the source did not quantify. The global-tier envelope is
#: UNVERIFIED, so `retry_after_seconds` being absent is plausible — and retrying
#: instantly against a server that just throttled us only deepens the breach.
_DEFAULT_RETRY_AFTER_SECONDS = 5.0


def _default_transport() -> Transport:
    from tools.ind_money import _call_mcp_tool  # imported lazily: needs env/auth
    from tools.ind_money_auth import get_access_token

    async def call(tool_name: str, arguments: Optional[dict]) -> Any:
        # Mint the token here rather than letting `_call_mcp_tool` do it: it
        # flattens MCPAuthError into an untyped MCPClientError string, which
        # destroys the only signal that separates "never linked" from "the
        # server is down". `_call` classifies what this lets through.
        await get_access_token()
        return await _call_mcp_tool(tool_name, arguments)

    return call


async def _default_auth_status() -> dict:
    from tools.ind_money_auth import auth_status

    return await auth_status()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class IndMoneyConnector(PortfolioConnector):
    """Read-only portfolio access to the IND Money MCP server.

    The process holds exactly **one** credential set (the operator's, cached in
    `backend/.ind_money_token.json`), so the connector is bound to a single
    ``user_id`` and refuses any other. F3 replaces that with a per-user link row;
    until then the guard is what stops a multi-user deployment from serving one
    person's portfolio to everybody.
    """

    source: ClassVar[str] = SOURCE

    def __init__(
        self,
        *,
        user_id: str = LOCAL_USER_ID,
        transport: Optional[Transport] = None,
        auth_status: Optional[Callable[[], Awaitable[dict]]] = None,
        clock: Callable[[], datetime] = _now_utc,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 2,
        max_retry_wait_seconds: float = 60.0,
        expiring_within_seconds: float = 300.0,
    ) -> None:
        self._user_id = user_id
        self._transport = transport or _default_transport()
        self._auth_status = auth_status or _default_auth_status
        self._clock = clock
        self._sleep = sleep
        self._max_retries = max(0, int(max_retries))
        self._max_retry_wait = float(max_retry_wait_seconds)
        self._expiring_within = float(expiring_within_seconds)
        self._revoked = False

    # ----------------------------------------------------------------- guards
    def _check_user(self, user_id: str) -> None:
        if not user_id:
            raise UserScopeError("user_id is required on every portfolio call")
        if user_id != self._user_id:
            raise UserScopeError(
                f"this connector is bound to user_id {self._user_id!r} and holds "
                f"exactly one credential set; it cannot serve {user_id!r}"
            )

    def mark_revoked(self) -> None:
        """Record that the source definitively rejected our credential."""
        self._revoked = True

    # ------------------------------------------------------------- call layer
    async def _call(self, tool: str, arguments: Optional[dict] = None) -> dict:
        """One tool call, with the rate-limit envelope handled before the payload.

        Retries are bounded and paced by the server's own
        ``retry_after_seconds`` — the only quantitative recovery signal it gives.
        The tier that tripped is read off the body (``scope`` / ``limit``), never
        assumed, because the per-tool and global tiers have different limits and
        the per-tool one trips first.
        """
        attempt = 0
        while True:
            payload = _require_mapping(tool, await self._invoke(tool, arguments))

            code = payload.get("error")
            # `error: false` and `error: ""` are not failures. Only a truthy
            # value is a source-reported error; treating any *present* key as
            # one would turn an ordinary payload into an exception.
            if not code:
                _assert_inr(tool, payload)
                return payload

            if code != _RATE_LIMIT_CODE:
                raise SourceReportedError(
                    tool,
                    str(code),
                    str(payload.get(_RL_MESSAGE) or ""),
                )

            limited = _rate_limited(tool, payload)
            if attempt >= self._max_retries:
                raise limited
            attempt += 1
            await self._sleep(self._backoff(limited.retry_after))

    async def _invoke(self, tool: str, arguments: Optional[dict]) -> Any:
        """Call the transport, translating every failure into a typed one.

        Without this, the MCP client's own exception escapes the abstraction and
        a caller writing ``except PortfolioSourceError`` silently misses it.
        """
        from tools.ind_money_auth import MCPAuthError, MCPAuthInvalid

        try:
            return await self._transport(tool, arguments)
        except PortfolioSourceError:
            raise
        except MCPAuthInvalid as exc:
            # Definitive: the stored credential is dead, not merely unlucky.
            self._revoked = True
            raise NotLinked(f"{tool}: not linked to IND Money ({exc})") from exc
        except MCPAuthError as exc:
            # Transient auth failure (network, 5xx): the credential may be fine.
            raise SourceUnavailable(f"{tool}: IND Money auth unavailable ({exc})") from exc
        except Exception as exc:  # noqa: BLE001 - transport failures are opaque
            raise SourceUnavailable(f"{tool}: IND Money call failed ({exc})") from exc

    def _backoff(self, retry_after: Optional[float]) -> float:
        """How long to wait: the source's own number, floored and capped."""
        wait = retry_after or 0.0
        if wait <= 0:
            wait = _DEFAULT_RETRY_AFTER_SECONDS
        return min(wait, self._max_retry_wait)

    # -------------------------------------------------------------- interface
    async def fetch_snapshot(self, user_id: str) -> PortfolioSnapshot:
        self._check_user(user_id)
        payload = await self._call(_TOOL_SNAPSHOT)
        as_of = self._clock()

        net_worth = _decimal_at(_TOOL_SNAPSHOT, "total_networth", payload.get("total_networth"))
        if net_worth is None:
            raise PayloadShapeError(
                f"{_TOOL_SNAPSHOT}: no total_networth in the payload — the "
                "aggregate total is the one field this snapshot cannot be built "
                "without"
            )

        liabilities = payload.get("liabilities")
        liabilities_total = (
            _decimal_at(_TOOL_SNAPSHOT, "liabilities.total", liabilities.get("total"))
            if isinstance(liabilities, dict)
            else None
        )

        sections: dict[str, list[AllocationSlice]] = {}
        for field, source_key, label_key in _SNAPSHOT_SECTIONS:
            sections[field] = [
                _slice(_TOOL_SNAPSHOT, f"{source_key}[{index}]", row, label_key)
                for index, row in enumerate(
                    _require_list(_TOOL_SNAPSHOT, payload, source_key)
                )
            ]

        return PortfolioSnapshot(
            source=self.source,
            as_of=as_of,
            # Totals are the vendor's own numbers, passed straight through. They
            # do not reconcile with a holdings sum and must not be recomputed.
            net_worth=net_worth,
            gross_value=_decimal_at(
                _TOOL_SNAPSHOT, "total_current_value", payload.get("total_current_value")
            ),
            invested_total=_decimal_at(
                _TOOL_SNAPSHOT, "total_invested", payload.get("total_invested")
            ),
            liabilities_total=liabilities_total,
            raw=payload,
            **sections,
        )

    async def fetch_holdings(self, user_id: str, asset_type: AssetType) -> list[Holding]:
        self._check_user(user_id)
        if asset_type is AssetType.UNKNOWN:
            raise UnsupportedAssetType(
                "IND Money cannot enumerate holdings for an asset type outside "
                "its own 16-value enum. The snapshot reports such buckets "
                "(US_STOCK_WALLET) but no call can list their line items — read "
                "them off fetch_snapshot().by_asset_type instead."
            )

        payload = await self._call(_TOOL_HOLDINGS, {"asset_type": asset_type.value})
        as_of = self._clock()

        # The live-trading envelope reports a broker-side fetch failure in a
        # flag while still returning `holdings: []`. Mapping that to an empty
        # list would render a FAILURE as an empty portfolio — the single most
        # dishonest thing this connector could do.
        failed = [flag for flag in _FETCH_ERROR_FLAGS if payload.get(flag)]
        if failed:
            raise SourceReportedError(
                _TOOL_HOLDINGS,
                failed[0],
                f"IND Money reported a broker-side fetch failure for "
                f"{asset_type.value} ({', '.join(failed)}); the holdings list is "
                "unreliable and must not be shown as an empty portfolio",
            )

        rows = _require_list(_TOOL_HOLDINGS, payload, "holdings")

        # IND_STOCK comes back inside a different, 19-key live-trading envelope
        # and its row shape has never been observed populated. Map it strictly.
        strict = asset_type is AssetType.IND_STOCK
        return [
            self._holding(row, asset_type, index, as_of, strict=strict)
            for index, row in enumerate(rows)
        ]

    async def fetch_allocation(
        self, user_id: str, asset_type: AssetType, by: BreakdownBy
    ) -> Allocation:
        self._check_user(user_id)
        if asset_type is AssetType.UNKNOWN:
            raise UnsupportedAssetType(
                "IND Money cannot break down an asset type outside its own enum"
            )

        payload = await self._call(
            _TOOL_BREAKDOWN,
            {"asset_type": asset_type.value, "breakdown_by": by.value},
        )
        as_of = self._clock()

        echoed = payload.get("asset_type"), payload.get("breakdown_by")
        if echoed != (asset_type.value, by.value):
            raise PayloadShapeError(
                f"{_TOOL_BREAKDOWN}: asked for "
                f"({asset_type.value}, {by.value}) and the payload echoed "
                f"{echoed} — refusing to attribute one slice's rows to another"
            )

        label_key = _BREAKDOWN_LABEL_KEY[by]
        return Allocation(
            source=self.source,
            asset_type=asset_type,
            by=by,
            as_of=as_of,
            slices=[
                _slice(_TOOL_BREAKDOWN, f"data[{index}]", row, label_key)
                for index, row in enumerate(
                    _require_list(_TOOL_BREAKDOWN, payload, "data")
                )
            ],
            raw=payload,
        )

    async def fetch_sips(self, user_id: str) -> list[Sip]:
        self._check_user(user_id)
        sips: list[Sip] = []
        for kind in (SipKind.MF, SipKind.IND_STOCK):
            payload = await self._call(_SIP_TOOL[kind])
            as_of = self._clock()
            rows = _require_list(_SIP_TOOL[kind], payload, _SIP_ROWS_KEY[kind])
            for index, row in enumerate(rows):
                sips.append(self._sip(row, kind, index, as_of))
        return sips

    async def link_health(self, user_id: str) -> LinkHealth:
        """Derive link health from the token's observed state.

        Note what is *not* done here: holding a refresh token is never treated as
        proof of health. The status provider actually verifies the credential
        (refreshing when it can), and a definitive rejection is reported as
        ``REVOKED`` rather than as a recoverable state.
        """
        self._check_user(user_id)
        if self._revoked:
            return LinkHealth.REVOKED

        from tools.ind_money_auth import MCPAuthError, MCPAuthInvalid

        try:
            status = await self._auth_status()
        except MCPAuthInvalid:
            self._revoked = True
            return LinkHealth.REVOKED
        except MCPAuthError:
            return LinkHealth.NEEDS_RELINK

        if not status.get("authenticated"):
            return LinkHealth.NEEDS_RELINK

        expires_in = status.get("expires_in_sec")
        if expires_in is None:  # a static bearer: no expiry to be inside of
            return LinkHealth.LINKED
        return (
            LinkHealth.EXPIRING
            if float(expires_in) <= self._expiring_within
            else LinkHealth.LINKED
        )

    # ---------------------------------------------------------------- mapping
    def _holding(
        self,
        row: Any,
        requested: AssetType,
        index: int,
        as_of: datetime,
        *,
        strict: bool,
    ) -> Holding:
        at = f"holdings[{index}]"
        if not isinstance(row, dict):
            raise PayloadShapeError(
                f"{_TOOL_HOLDINGS}: expected an object at {at}, got "
                f"{type(row).__name__}"
            )

        if strict:
            # The IND_STOCK boundary: a shape we have documented but never seen
            # populated. "Matches the documented shape" means the WHOLE 14-key
            # set (bar the legitimately-absent cost basis) — a row missing five
            # of them is not a row we have any business guessing at.
            unexpected = set(row) - _ROW_KEYS
            missing = _ROW_STRICT_KEYS - set(row)
            if unexpected or missing:
                raise UnverifiedShapeError(
                    "IND_STOCK holdings row does not match the documented "
                    "aggregator shape — this boundary is UNVERIFIED (no "
                    f"populated row has ever been observed). unexpected keys: "
                    f"{sorted(unexpected)}; missing keys: {sorted(missing)}"
                )

        raw_type = row.get("asset_type")
        raw_type = raw_type if isinstance(raw_type, str) and raw_type.strip() else requested.value
        asset_type = AssetType.coerce(raw_type)

        current_value = _decimal_at(
            _TOOL_HOLDINGS, f"{at}.market_value", row.get("market_value")
        )
        if current_value is None:
            raise PayloadShapeError(
                f"{_TOOL_HOLDINGS}: {at} has no value; current_value is "
                "the one number every row is required to carry"
            )

        # 0 is the vendor's documented stand-in for "cost basis unknown".
        invested = _decimal_at(
            _TOOL_HOLDINGS, f"{at}.invested_amount", row.get("invested_amount")
        )
        if invested == 0:
            invested = None

        units = _decimal_at(_TOOL_HOLDINGS, f"{at}.total_units", row.get("total_units"))
        price = _decimal_at(_TOOL_HOLDINGS, f"{at}.unit_price", row.get("unit_price"))
        if current_value != 0 and units == 0 and price == 0:
            # Cash-like rows (savings, deposits) carry no unit/price
            # decomposition at all — reporting 0 would read as a real price.
            units = None
            price = None

        pnl: Optional[Decimal] = None
        pnl_pct: Optional[Decimal] = None
        if invested is not None:
            # Prefer the source's own figures; they are legitimately 0 on
            # cash-like rows, which is a real answer, not a missing one.
            pnl = _decimal_at(_TOOL_HOLDINGS, f"{at}.total_pnl", row.get("total_pnl"))
            pnl_pct = _decimal_at(_TOOL_HOLDINGS, f"{at}.pnl_per", row.get("pnl_per"))
            if pnl is None or pnl_pct is None:
                pnl, pnl_pct = derive_pnl(current_value, invested)

        avg_cost: Optional[Decimal] = None
        if invested is not None and units not in (None, 0):
            avg_cost = (invested / units).quantize(Decimal("0.0001"))

        code = row.get("investment_code")
        code = code.strip() if isinstance(code, str) else ""
        if code:
            external_id = f"{raw_type}:{code}"
        else:
            # No instrument id. The descriptive fields alone are NOT enough:
            # two rows can carry an empty name, an empty broker and the same
            # classification labels, and hashing only those merges two real
            # positions into one — the exact failure the primary id avoids.
            # The row's position in the response is therefore folded in, which
            # guarantees uniqueness *within* a response at the cost of
            # stability *across* them. That trade is deliberate and documented
            # in SPECS/M1 §2: churning one id is recoverable, silently merging
            # two holdings is not.
            external_id = "{}:h:{}".format(
                raw_type,
                stable_external_id(
                    row.get("investment"),
                    row.get("broker"),
                    row.get("assetclass_l2"),
                    row.get("market_cap"),
                    index,
                ),
            )

        name = row.get("investment")
        name = name.strip() if isinstance(name, str) else None

        return Holding(
            source=self.source,
            external_id=external_id,
            asset_type=asset_type,
            asset_type_raw=raw_type,
            # IND Money keys instruments by its own code and publishes no ticker
            # or ISIN on a holdings row.
            symbol=None,
            isin=None,
            name=name or None,
            units=units,
            avg_cost=avg_cost,
            invested_amount=invested,
            current_price=price,
            current_value=current_value,
            pnl=pnl,
            pnl_pct=pnl_pct,
            as_of=as_of,
            raw=row,
        )

    def _sip(self, row: Any, kind: SipKind, index: int, as_of: datetime) -> Sip:
        if not isinstance(row, dict):
            raise PayloadShapeError(
                f"{_SIP_TOOL[kind]}: expected an object per SIP, got "
                f"{type(row).__name__}"
            )
        identifier = _first_str(row, _SIP_ID_KEYS) or f"{index}"
        return Sip(
            source=self.source,
            external_id=f"{kind.value}:{identifier}",
            kind=kind,
            name=_first_str(row, _SIP_NAME_KEYS),
            amount=_decimal_at(
                _SIP_TOOL[kind], f"{_SIP_ROWS_KEY[kind]}[{index}].amount",
                _first(row, _SIP_AMOUNT_KEYS),
            ),
            frequency=_first_str(row, _SIP_FREQUENCY_KEYS),
            next_execution_at=_parse_datetime(_first_str(row, _SIP_NEXT_KEYS)),
            status=_first_str(row, _SIP_STATUS_KEYS),
            as_of=as_of,
            raw=row,
        )


# --------------------------------------------------------------------------- #
# Payload helpers
# --------------------------------------------------------------------------- #
def _rate_limited(tool: str, body: dict) -> RateLimited:
    """Read IND Money's throttle body into the source-neutral carrier.

    This lives here, not on the exception, because every key name below is IND
    Money's. `RateLimited` itself knows only the normalized facts.
    """

    def number(key: str) -> Optional[float]:
        value: Any = body.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def text(key: str) -> Optional[str]:
        value = body.get(key)
        return value if isinstance(value, str) else None

    return RateLimited(
        # The body names the tool that tripped; fall back to the caller's.
        text(_RL_TOOL) or tool,
        _RATE_LIMIT_CODE,
        message=text(_RL_MESSAGE) or "",
        scope=text(_RL_SCOPE),
        window=text(_RL_WINDOW),
        limit=number(_RL_LIMIT),
        current=number(_RL_CURRENT),
        cost=number(_RL_COST),
        retry_after=number(_RL_RETRY_AFTER),
        body=body,
    )


def _decimal_at(tool: str, path: str, value: Any) -> Optional[Decimal]:
    """`to_decimal`, with a typed failure and no value in the message.

    A thousands separator, an empty object, a NaN — every one of these is a
    payload the documented shape does not cover, and every one of them would
    otherwise escape mapping as a bare `ValueError` (or, for NaN, as a pydantic
    `ValidationError` several frames later) that no caller is catching.
    """
    try:
        parsed = to_decimal(value)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise PayloadShapeError(
            f"{tool}: {path} is not a usable number (value withheld)"
        ) from exc
    return parsed


def _require_mapping(tool: str, payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise PayloadShapeError(
            f"{tool}: expected a JSON object, got {type(payload).__name__}"
        )
    return payload


def _require_list(tool: str, payload: dict, key: str) -> list:
    value = payload.get(key)
    if value is None:
        raise PayloadShapeError(
            f"{tool}: payload has no {key!r}. A throttled call replaces the "
            "payload with an error body, so this is also what a missed "
            "rate-limit check looks like"
        )
    if not isinstance(value, list):
        raise PayloadShapeError(
            f"{tool}: expected {key!r} to be a list, got {type(value).__name__}"
        )
    return value


def _assert_inr(tool: str, node: Any, path: str = "") -> None:
    """Raise if the payload declares a currency and it is not INR.

    No observed payload carries one at any level (C2 Q4), and the vendor sums US
    holdings into its own INR totals — so the appearance of a disagreeing
    currency falsifies v2's whole currency stance and must stop the caller.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if "currency" in str(key).lower():
                if isinstance(value, str) and value.strip():
                    if value.strip().upper() != "INR":
                        raise NonInrValue(tool, here, value)
                elif value is not None:
                    raise NonInrValue(tool, here, value)
            _assert_inr(tool, value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _assert_inr(tool, value, f"{path}[{index}]")


def _slice(tool: str, at: str, row: Any, label_key: str) -> AllocationSlice:
    if not isinstance(row, dict):
        raise PayloadShapeError(
            f"{tool}: expected an object at {at}, got {type(row).__name__}"
        )
    current_value = _decimal_at(tool, f"{at}.current_value", row.get("current_value"))
    if current_value is None:
        raise PayloadShapeError(f"{tool}: {at} has no current value")

    # Same rule as a holding row: 0 is the source's stand-in for "unknown", so
    # the bucket's own return becomes unknowable with it.
    invested = _decimal_at(tool, f"{at}.invested_value", row.get("invested_value"))
    if invested == 0:
        invested = None

    pnl = (
        _decimal_at(tool, f"{at}.return", row.get("return"))
        if invested is not None
        else None
    )
    pnl_pct = (
        _decimal_at(tool, f"{at}.return_percentage", row.get("return_percentage"))
        if invested is not None
        else None
    )

    label = row.get(label_key)
    label = label.strip() if isinstance(label, str) else ""
    asset_type = AssetType.coerce(label) if label_key == "asset_type" else None

    return AllocationSlice(
        label=label,
        asset_type=asset_type,
        asset_type_raw=label if label_key == "asset_type" else None,
        invested_amount=invested,
        current_value=current_value,
        pnl=pnl,
        pnl_pct=pnl_pct,
        weight_pct=_decimal_at(
            tool, f"{at}.progress_value_percentage", row.get("progress_value_percentage")
        ),
        raw=row,
    )


def _first(row: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def _first_str(row: dict, keys: tuple[str, ...]) -> Optional[str]:
    value = _first(row, keys)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Best-effort ISO parse, stamped UTC when the source omits a zone.

    The SIP row shape is unverified, so an unparseable value is left as ``None``
    and preserved in ``raw`` rather than guessed at.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = ["IndMoneyConnector", "SOURCE"]
