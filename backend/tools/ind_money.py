"""IND Money MCP server wrapped as LangGraph tools (read-only market data).

Connects to the IND Money MCP over streamable HTTP (URL in ``IND_MONEY_MCP_URL``)
with an OAuth bearer token from ``ind_money_auth.get_access_token()``. Each tool is
an async LangChain ``@tool`` returning a typed Pydantic model, or a clear error
string on failure.

The IND Money API keys every instrument by ``ind_key`` (e.g. "INDS00577"), not by
ticker symbol. Resolve a ticker/name to an ind_key with ``lookup_ind_keys`` or read
it off ``get_indian_stocks_movers``. Responses are wrapped as
``{"result": "<stringified JSON>"}`` and unwrapped here.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, ConfigDict, Field

from tools.ind_money_auth import MCPAuthError, get_access_token

# Valid categories for get_indian_stocks_movers (from the live tool schema).
MOVER_CATEGORIES = (
    "top-gainers",
    "top-losers",
    "most-active",
    "52-week-high",
    "52-week-low",
    "upper-circuit-stocks",
    "lower-circuit-stocks",
)


# --------------------------------------------------------------------------- #
# MCP client plumbing
# --------------------------------------------------------------------------- #
class MCPClientError(Exception):
    """Raised when an IND Money MCP call cannot be completed."""


def _extract_text(result: Any) -> Optional[str]:
    parts: List[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts) if parts else None


def _unwrap(data: Any) -> Any:
    """Unwrap IND Money's ``{"result": "<stringified JSON>"}`` envelope."""
    for _ in range(4):
        if isinstance(data, str):
            try:
                data = json.loads(data)
                continue
            except json.JSONDecodeError:
                return data
        if isinstance(data, dict) and list(data.keys()) == ["result"]:
            data = data["result"]
            continue
        break
    return data


async def _call_mcp_tool(tool_name: str, arguments: Optional[dict] = None) -> Any:
    """Call ``tool_name`` on the IND Money MCP and return the unwrapped JSON.

    Raises ``MCPClientError`` on missing URL/auth, transport, or tool-level errors.
    """
    url = os.environ.get("IND_MONEY_MCP_URL")
    if not url:
        raise MCPClientError("IND_MONEY_MCP_URL is not set")

    # None values are dropped; required args must be supplied by the wrapper.
    args = {k: v for k, v in (arguments or {}).items() if v is not None}

    try:
        token = await get_access_token()
    except MCPAuthError as exc:
        raise MCPClientError(str(exc))

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args)

    if getattr(result, "isError", False):
        raise MCPClientError(_extract_text(result) or f"{tool_name} returned an error")

    structured = getattr(result, "structuredContent", None)
    if structured:
        return _unwrap(structured)

    text = _extract_text(result)
    if text is None:
        raise MCPClientError(f"{tool_name} returned no content")
    try:
        return _unwrap(json.loads(text))
    except json.JSONDecodeError:
        return _unwrap(text)


def _pick_list(data: Any, *aliases: str) -> List[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for alias in aliases:
            v = data.get(alias)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _scalars(data: Any) -> dict:
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if not isinstance(v, (list, dict))}


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #
class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


class OHLCBar(_Base):
    timestamp_sec: Optional[int] = None
    datetime_ist: Optional[str] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None


class OHLCResponse(_Base):
    ind_key: Optional[str] = None
    interval: Optional[str] = None
    count: Optional[int] = None
    has_more_data: Optional[bool] = None
    bars: List[OHLCBar] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "OHLCResponse":
        bars = _pick_list(data, "candles", "bars", "ohlc", "data")
        return cls(bars=[OHLCBar(**b) for b in bars], **_scalars(data))


class MoverStock(_Base):
    ind_key: Optional[str] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    exchange: Optional[str] = None
    sector: Optional[str] = None
    market_cap_category: Optional[str] = None
    price: Optional[float] = None
    change_pct: Optional[float] = None
    abs_change: Optional[float] = None
    previous_close: Optional[float] = None
    volume: Optional[float] = None
    mcap_cr: Optional[float] = None


class MoversResponse(_Base):
    category: Optional[str] = None
    count: Optional[int] = None
    stocks: List[MoverStock] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "MoversResponse":
        stocks = _pick_list(data, "stocks", "movers", "data")
        return cls(stocks=[MoverStock(**s) for s in stocks], **_scalars(data))


class IndKey(_Base):
    ind_key: Optional[str] = None
    name: Optional[str] = None


class IndKeysResponse(_Base):
    keys: List[IndKey] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "IndKeysResponse":
        items = data if isinstance(data, list) else _pick_list(data, "keys", "results", "matches", "data")
        return cls(keys=[IndKey(**k) for k in items if isinstance(k, dict)])


class StockDetail(_Base):
    ind_key: Optional[str] = None
    name: Optional[str] = None
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    market_cap: Optional[str] = None
    market_cap_in_currency: Optional[float] = None
    has_fno: Optional[bool] = None
    live_price: Optional[float] = None
    day_change_percentage: Optional[float] = None
    prev_close: Optional[float] = None
    day_low: Optional[float] = None
    day_high: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None


class StockDetailsResponse(_Base):
    details: Dict[str, StockDetail] = Field(default_factory=dict)

    @classmethod
    def from_mcp(cls, data: Any) -> "StockDetailsResponse":
        out: Dict[str, StockDetail] = {}
        if isinstance(data, dict):
            for key, ent in data.items():
                if not isinstance(ent, dict):
                    continue
                eb = ent.get("entity_basic") or {}
                es = ent.get("entity_stats") or {}
                out[key] = StockDetail(
                    ind_key=eb.get("ind_key", key),
                    name=eb.get("name"),
                    symbol=eb.get("symbol"),
                    exchange=eb.get("exchange"),
                    market_cap=eb.get("market_cap"),
                    market_cap_in_currency=eb.get("market_cap_in_currency"),
                    has_fno=eb.get("has_fno"),
                    live_price=es.get("live_price"),
                    day_change_percentage=es.get("day_change_percentage"),
                    prev_close=es.get("prev_close"),
                    day_low=es.get("day_low"),
                    day_high=es.get("day_high"),
                    week52_high=es.get("52week_high"),
                    week52_low=es.get("52week_low"),
                )
        return cls(details=out)


class OptionChainResponse(_Base):
    ind_key: Optional[str] = None
    expiry_date: Optional[str] = None
    strikes: List[dict] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "OptionChainResponse":
        strikes = _pick_list(data, "strikes", "option_chain", "chain", "options", "data")
        return cls(strikes=strikes, **_scalars(data))


class GreeksHistoryResponse(_Base):
    ind_key: Optional[str] = None
    snapshots: List[dict] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "GreeksHistoryResponse":
        snaps = _pick_list(data, "snapshots", "history", "greeks", "data")
        return cls(snapshots=snaps, **_scalars(data))


class WatchlistStock(_Base):
    ind_key: Optional[str] = None
    ticker: Optional[str] = None


class Watchlist(_Base):
    name: Optional[str] = None
    watchlist_id: Optional[int] = None
    stocks: List[WatchlistStock] = Field(default_factory=list)


class WatchlistResponse(_Base):
    type: Optional[str] = None
    watchlists: List[Watchlist] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "WatchlistResponse":
        lists = _pick_list(data, "watchlists", "data")
        parsed = []
        for wl in lists:
            stocks = [WatchlistStock(**s) for s in (wl.get("stocks") or []) if isinstance(s, dict)]
            parsed.append(Watchlist(stocks=stocks, **{k: v for k, v in wl.items() if k != "stocks"}))
        return cls(watchlists=parsed, **_scalars(data))


# --------------------------------------------------------------------------- #
# LangGraph tools
# --------------------------------------------------------------------------- #
@tool
async def get_indian_stocks_movers(category: str, limit: int = 10) -> MoversResponse | str:
    """Fetch NSE market movers for a category.

    Args:
        category: One of top-gainers, top-losers, most-active, 52-week-high,
                  52-week-low, upper-circuit-stocks, lower-circuit-stocks.
        limit: Number of stocks to return (default 10).
    """
    try:
        data = await _call_mcp_tool(
            "get_indian_stocks_movers", {"category": category, "limit": limit}
        )
        return MoversResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching movers ({category}): {exc}"


@tool
async def lookup_ind_keys(names: List[str], filter_type: Optional[str] = None) -> IndKeysResponse | str:
    """Resolve company names / tickers to IND Money ind_keys.

    Args:
        names: Names or tickers to look up, e.g. ["INFY", "Reliance"].
        filter_type: Optional instrument-type filter.
    """
    try:
        data = await _call_mcp_tool(
            "lookup_ind_keys", {"names": names, "filter_type": filter_type}
        )
        return IndKeysResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error looking up ind keys for {names}: {exc}"


@tool
async def get_indian_stocks_details(
    ind_keys: List[str],
    segments: Optional[List[str]] = None,
) -> StockDetailsResponse | str:
    """Fetch fundamental + quote details for one or more NSE instruments.

    Args:
        ind_keys: IND Money ind_keys, e.g. ["INDS00577"].
        segments: Optional extra segments — any of "analyst", "news".
    """
    try:
        data = await _call_mcp_tool(
            "get_indian_stocks_details", {"ind_keys": ind_keys, "segments": segments}
        )
        return StockDetailsResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching details for {ind_keys}: {exc}"


@tool
async def get_indian_stocks_ohlc(
    ind_key: str,
    interval: str = "1day",
    lookback: str = "3month",
) -> OHLCResponse | str:
    """Fetch OHLC candles for an NSE instrument.

    Args:
        ind_key: IND Money ind_key, e.g. "INDS00577".
        interval: Candle interval, e.g. "1day".
        lookback: Look-back window, e.g. "1month", "3month", "1year".
    """
    try:
        data = await _call_mcp_tool(
            "get_indian_stocks_ohlc",
            {"ind_key": ind_key, "interval": interval, "lookback": lookback},
        )
        return OHLCResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching OHLC for {ind_key}: {exc}"


@tool
async def get_indian_stocks_option_chain(
    ind_key: str,
    use_expiry_date: bool = False,
    expiry_date: Optional[str] = None,
    strikes_around_atm: Optional[int] = None,
) -> OptionChainResponse | str:
    """Fetch the option chain for an NSE underlying (F&O only).

    Args:
        ind_key: Underlying IND Money ind_key.
        use_expiry_date: Whether to filter by a specific expiry_date.
        expiry_date: Expiry date to use when use_expiry_date is True.
        strikes_around_atm: How many strikes around at-the-money to return.
    """
    try:
        data = await _call_mcp_tool(
            "get_indian_stocks_option_chain",
            {
                "ind_key": ind_key,
                "use_expiry_date": use_expiry_date,
                "expiry_date": expiry_date,
                "strikes_around_atm": strikes_around_atm,
            },
        )
        return OptionChainResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching option chain for {ind_key}: {exc}"


@tool
async def get_indian_stocks_greeks_history(
    ind_key: str,
    lookback: Optional[str] = None,
) -> GreeksHistoryResponse | str:
    """Fetch historical option greeks for an NSE underlying (F&O only).

    Args:
        ind_key: Underlying IND Money ind_key.
        lookback: Optional look-back window, e.g. "1month".
    """
    try:
        data = await _call_mcp_tool(
            "get_indian_stocks_greeks_history",
            {"ind_key": ind_key, "lookback": lookback},
        )
        return GreeksHistoryResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching greeks history for {ind_key}: {exc}"


@tool
async def user_watchlist(type: str = "all") -> WatchlistResponse | str:
    """Read the user's IND Money watchlists (read-only).

    NOTE: the IND Money MCP cannot modify watchlists. AlphaDesk uses its own
    paper watchlist for adds; this tool only reads existing watchlists.

    Args:
        type: Which watchlists to return, e.g. "all".
    """
    try:
        data = await _call_mcp_tool("user_watchlist", {"type": type})
        return WatchlistResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error reading watchlist: {exc}"
