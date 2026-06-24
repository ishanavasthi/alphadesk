"""IND Money MCP server wrapped as LangGraph tools (read-only market data).

Connects to the IND Money MCP server over streamable HTTP using the URL in the
``IND_MONEY_MCP_URL`` environment variable. Each of the seven tools below is an
async LangChain ``@tool`` that returns a typed Pydantic model on success, or a
clear human-readable error string if the underlying MCP call fails.

The exact JSON shape returned by the live IND Money MCP server is not known at
scaffold time, so the response models allow extra fields (``extra="allow"``) and
the ``from_mcp`` constructors pull list payloads from a few likely key aliases.
Tighten the field mappings once the real server schema is confirmed.
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Optional

from langchain_core.tools import tool
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# MCP client plumbing
# --------------------------------------------------------------------------- #
class MCPClientError(Exception):
    """Raised when an IND Money MCP call cannot be completed."""


def _extract_text(result: Any) -> Optional[str]:
    """Return the concatenated text of any TextContent blocks in a tool result."""
    parts: List[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts) if parts else None


def _unwrap(data: Any) -> Any:
    """Unwrap IND Money's nested response envelope.

    The IND Money MCP returns payloads as ``{"result": "<stringified JSON>"}`` —
    the actual data is a JSON string nested under ``result``. Repeatedly unwrap a
    sole ``result`` key and re-parse any JSON string until we reach the real
    object (bounded to avoid pathological loops).
    """
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
    """Open a session to the IND Money MCP server, call ``tool_name``, return JSON.

    Returns the tool's structured content when present, otherwise the parsed JSON
    text payload (falling back to the raw text). Raises ``MCPClientError`` on any
    transport, protocol, or tool-level error.
    """
    url = os.environ.get("IND_MONEY_MCP_URL")
    if not url:
        raise MCPClientError("IND_MONEY_MCP_URL is not set")

    args = {k: v for k, v in (arguments or {}).items() if v is not None}

    async with streamablehttp_client(url) as (read_stream, write_stream, _):
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
    """Find the first list payload in ``data``, trying ``aliases`` keys if a dict."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for alias in aliases:
            value = data.get(alias)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _scalars(data: Any) -> dict:
    """Top-level scalar fields of ``data`` (kept via ``extra="allow"``)."""
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
    timestamp: Optional[str] = None  # legacy/alt field name, kept for forward-compat


class OHLCResponse(_Base):
    ind_key: Optional[str] = Field(None, description="IND Money internal instrument key.")
    symbol: Optional[str] = None
    interval: Optional[str] = Field(None, description="Candle interval, e.g. '1day'.")
    count: Optional[int] = Field(None, description="Number of candles returned.")
    has_more_data: Optional[bool] = Field(
        None, description="True when the server has older candles beyond this page."
    )
    bars: List[OHLCBar] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "OHLCResponse":
        # Real IND Money key is "candles"; aliases kept for other shapes.
        bars = _pick_list(data, "candles", "bars", "ohlc", "data")
        return cls(bars=[OHLCBar(**b) for b in bars], **_scalars(data))


class StockDetails(_Base):
    symbol: Optional[str] = None
    name: Optional[str] = None
    sector: Optional[str] = None
    last_price: Optional[float] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None

    @classmethod
    def from_mcp(cls, data: Any) -> "StockDetails":
        if isinstance(data, dict):
            return cls(**data)
        return cls()


class MoverItem(_Base):
    symbol: Optional[str] = None
    name: Optional[str] = None
    last_price: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None


class MoversResponse(_Base):
    gainers: List[MoverItem] = Field(default_factory=list)
    losers: List[MoverItem] = Field(default_factory=list)
    most_active: List[MoverItem] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "MoversResponse":
        return cls(
            gainers=[MoverItem(**m) for m in _pick_list(data, "gainers", "top_gainers")],
            losers=[MoverItem(**m) for m in _pick_list(data, "losers", "top_losers")],
            most_active=[MoverItem(**m) for m in _pick_list(data, "most_active", "active")],
            **_scalars(data),
        )


class OptionStrike(_Base):
    strike_price: Optional[float] = None
    call_ltp: Optional[float] = None
    call_oi: Optional[float] = None
    call_iv: Optional[float] = None
    put_ltp: Optional[float] = None
    put_oi: Optional[float] = None
    put_iv: Optional[float] = None


class OptionChainResponse(_Base):
    symbol: Optional[str] = None
    expiry: Optional[str] = None
    underlying_price: Optional[float] = None
    strikes: List[OptionStrike] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "OptionChainResponse":
        strikes = _pick_list(data, "strikes", "option_chain", "chain", "data")
        return cls(strikes=[OptionStrike(**s) for s in strikes], **_scalars(data))


class GreeksSnapshot(_Base):
    timestamp: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None
    iv: Optional[float] = None


class GreeksHistoryResponse(_Base):
    symbol: Optional[str] = None
    snapshots: List[GreeksSnapshot] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "GreeksHistoryResponse":
        snaps = _pick_list(data, "snapshots", "history", "greeks", "data")
        return cls(snapshots=[GreeksSnapshot(**s) for s in snaps], **_scalars(data))


class IndKey(_Base):
    symbol: Optional[str] = None
    name: Optional[str] = None
    ind_key: Optional[str] = None


class IndKeysResponse(_Base):
    keys: List[IndKey] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "IndKeysResponse":
        keys = _pick_list(data, "keys", "results", "matches", "data")
        return cls(keys=[IndKey(**k) for k in keys], **_scalars(data))


class WatchlistItem(_Base):
    symbol: Optional[str] = None
    name: Optional[str] = None
    added_at: Optional[str] = None


class WatchlistResponse(_Base):
    action: Optional[str] = None
    status: Optional[str] = None
    items: List[WatchlistItem] = Field(default_factory=list)

    @classmethod
    def from_mcp(cls, data: Any) -> "WatchlistResponse":
        items = _pick_list(data, "items", "watchlist", "stocks", "data")
        return cls(items=[WatchlistItem(**i) for i in items], **_scalars(data))


# --------------------------------------------------------------------------- #
# LangGraph tools (Scanner / Research / Analyst / Execution use these)
# --------------------------------------------------------------------------- #
@tool
async def get_indian_stocks_ohlc(
    symbol: str,
    interval: Optional[str] = None,
    range: Optional[str] = None,
) -> OHLCResponse | str:
    """Fetch OHLC (open/high/low/close/volume) candles for an NSE stock.

    Args:
        symbol: NSE ticker symbol, e.g. "RELIANCE".
        interval: Candle interval, e.g. "1d", "1h" (optional).
        range: Look-back window, e.g. "1mo", "1y" (optional).
    """
    try:
        data = await _call_mcp_tool(
            "get_indian_stocks_ohlc",
            {"symbol": symbol, "interval": interval, "range": range},
        )
        return OHLCResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the agent
        return f"Error fetching OHLC for {symbol}: {exc}"


@tool
async def get_indian_stocks_details(symbol: str) -> StockDetails | str:
    """Fetch fundamental and quote details for a single NSE stock.

    Args:
        symbol: NSE ticker symbol, e.g. "TCS".
    """
    try:
        data = await _call_mcp_tool("get_indian_stocks_details", {"symbol": symbol})
        return StockDetails.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching details for {symbol}: {exc}"


@tool
async def get_indian_stocks_movers(category: Optional[str] = None) -> MoversResponse | str:
    """Fetch market movers (gainers, losers, most active) for NSE.

    Args:
        category: Optional filter, e.g. "gainers", "losers", "most_active".
                  When omitted, all categories are returned.
    """
    try:
        data = await _call_mcp_tool("get_indian_stocks_movers", {"category": category})
        return MoversResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching market movers: {exc}"


@tool
async def get_indian_stocks_option_chain(
    symbol: str,
    expiry: Optional[str] = None,
) -> OptionChainResponse | str:
    """Fetch the option chain for an NSE underlying.

    Args:
        symbol: Underlying NSE symbol, e.g. "NIFTY" or "RELIANCE".
        expiry: Expiry date (e.g. "2026-06-25"). Defaults to nearest expiry.
    """
    try:
        data = await _call_mcp_tool(
            "get_indian_stocks_option_chain",
            {"symbol": symbol, "expiry": expiry},
        )
        return OptionChainResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching option chain for {symbol}: {exc}"


@tool
async def get_indian_stocks_greeks_history(
    symbol: str,
    expiry: Optional[str] = None,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
) -> GreeksHistoryResponse | str:
    """Fetch the historical option greeks for an NSE contract.

    Args:
        symbol: Underlying NSE symbol, e.g. "NIFTY".
        expiry: Expiry date of the contract (optional).
        strike: Strike price of the contract (optional).
        option_type: "CE" (call) or "PE" (put) (optional).
    """
    try:
        data = await _call_mcp_tool(
            "get_indian_stocks_greeks_history",
            {
                "symbol": symbol,
                "expiry": expiry,
                "strike": strike,
                "option_type": option_type,
            },
        )
        return GreeksHistoryResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error fetching greeks history for {symbol}: {exc}"


@tool
async def lookup_ind_keys(query: str) -> IndKeysResponse | str:
    """Resolve a name or symbol to IND Money internal keys/identifiers.

    Args:
        query: Company name or ticker to look up, e.g. "Infosys".
    """
    try:
        data = await _call_mcp_tool("lookup_ind_keys", {"query": query})
        return IndKeysResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error looking up ind keys for '{query}': {exc}"


@tool
async def user_watchlist(
    action: str = "get",
    symbol: Optional[str] = None,
) -> WatchlistResponse | str:
    """Read or modify the user's watchlist.

    NOTE: write actions ("add"/"remove") must only be invoked by the Execution
    agent after ``human_approved`` is True in state.

    Args:
        action: "get" to list, "add" to add a symbol, "remove" to remove one.
        symbol: NSE ticker the action applies to (required for add/remove).
    """
    try:
        data = await _call_mcp_tool(
            "user_watchlist",
            {"action": action, "symbol": symbol},
        )
        return WatchlistResponse.from_mcp(data)
    except Exception as exc:  # noqa: BLE001
        return f"Error accessing watchlist (action={action}): {exc}"
