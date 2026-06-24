"""Scanner agent — turns a natural-language query into NSE candidates.

Pure async node ``(state: PortfolioState) -> PortfolioState``. Uses
``llama-3.1-8b-instant`` to read intent from ``state.user_query`` — which mover
categories to scan and which explicit tickers/companies to pull — then:

  - calls ``get_indian_stocks_movers`` for each category (rich rows: ind_key,
    symbol, sector, price, change_pct, volume), and
  - resolves any named symbols via ``lookup_ind_keys`` + ``get_indian_stocks_details``.

Writes the top 5 opportunities (with ind_key + sector) into ``state.scan_results``.
"""

from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Optional

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from graph.state import PortfolioState, ScanResult
from tools.ind_money import (
    MOVER_CATEGORIES,
    IndKeysResponse,
    MoversResponse,
    StockDetailsResponse,
    get_indian_stocks_details,
    get_indian_stocks_movers,
    lookup_ind_keys,
)

SCANNER_MODEL = "llama-3.1-8b-instant"
MAX_OPPORTUNITIES = 5  # cap for a momentum (movers) scan
_MAX_NAMED = 12  # cap when the user named explicit stocks
_MOVERS_LIMIT = 8


def _get_llm() -> ChatGroq:
    return ChatGroq(model=SCANNER_MODEL, temperature=0)


class _Intent(BaseModel):
    categories: List[str] = Field(
        default_factory=list, description="Mover categories to scan (from the allowed enum)."
    )
    symbols: List[str] = Field(
        default_factory=list, description="Explicit tickers or company names named in the query."
    )


class _Candidate(BaseModel):
    ind_key: Optional[str] = None
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    price: Optional[float] = None
    change_pct: Optional[float] = None
    source: str


def _heuristic_intent(query: str) -> _Intent:
    """Fallback intent parse when the LLM is unavailable."""
    q = query.lower()
    if any(w in q for w in ("loser", "oversold", "fall", "down", "decline")):
        category = "top-losers"
    elif any(w in q for w in ("active", "volume", "liquid")):
        category = "most-active"
    elif "52" in q and "low" in q:
        category = "52-week-low"
    elif "52" in q and "high" in q:
        category = "52-week-high"
    else:
        category = "top-gainers"
    # Uppercase tokens look like tickers (e.g. "INFY", "TCS").
    symbols = [t for t in re.findall(r"\b[A-Z]{2,12}\b", query) if t not in {"NSE", "BSE", "IT", "FNO"}]
    return _Intent(categories=[category], symbols=symbols)


async def _intent(query: str) -> _Intent:
    prompt = (
        "You route an equity-research query to a market scanner.\n"
        f"Allowed mover categories: {', '.join(MOVER_CATEGORIES)}.\n"
        "Pick the categories that fit the query's intent (momentum->top-gainers, "
        "oversold/weakness->top-losers, liquidity->most-active, breakouts->52-week-high).\n"
        "Also extract any explicit tickers or company names mentioned (symbols).\n"
        "If the query names specific stocks, you may return no categories.\n\n"
        f"Query: {query}"
    )
    try:
        llm = _get_llm().with_structured_output(_Intent)
        out = await llm.ainvoke(prompt)
        cats = [c for c in (out.categories or []) if c in MOVER_CATEGORIES]
        intent = _Intent(categories=cats, symbols=out.symbols or [])
    except Exception:  # noqa: BLE001
        intent = _heuristic_intent(query)
    if not intent.categories and not intent.symbols:
        intent.categories = ["top-gainers"]
    return intent


async def _from_movers(category: str) -> List[_Candidate]:
    res = await get_indian_stocks_movers.ainvoke({"category": category, "limit": _MOVERS_LIMIT})
    if not isinstance(res, MoversResponse):
        return []
    out = []
    for s in res.stocks:
        if not s.symbol:
            continue
        out.append(
            _Candidate(
                ind_key=s.ind_key,
                symbol=s.symbol,
                name=s.name,
                sector=s.sector,
                price=s.price,
                change_pct=s.change_pct,
                source=f"movers:{category}",
            )
        )
    return out


async def _resolve_one(name: str) -> Optional[tuple]:
    """Resolve a single name to its best (ind_key, name) match."""
    res = await lookup_ind_keys.ainvoke({"names": [name]})
    if isinstance(res, IndKeysResponse) and res.keys:
        top = res.keys[0]
        if top.ind_key:
            return (top.ind_key, top.name)
    return None


async def _from_symbols(symbols: List[str]) -> List[_Candidate]:
    """Resolve each named stock to its best match — one lookup per name.

    Per-name lookup avoids batch fuzzy-noise + truncation: every requested name
    gets its own top hit (not an exact-ticker re-match), then details are fetched
    in a single batch. Order follows the request.
    """
    # Split combined tokens like "TV18/Network18" into separate names.
    names: List[str] = []
    for s in symbols:
        for part in s.split("/"):
            p = part.strip()
            if p and p not in names:
                names.append(p)
    if not names:
        return []

    resolved = await asyncio.gather(*(_resolve_one(n) for n in names), return_exceptions=True)

    ind_keys: List[str] = []
    lk_names: Dict[str, Optional[str]] = {}
    for r in resolved:
        if isinstance(r, tuple):
            ik, nm = r
            if ik not in lk_names:
                ind_keys.append(ik)
                lk_names[ik] = nm
    if not ind_keys:
        return []

    details = await get_indian_stocks_details.ainvoke({"ind_keys": ind_keys, "segments": None})
    detail_by_key = details.details if isinstance(details, StockDetailsResponse) else {}

    out: List[_Candidate] = []
    for ik in ind_keys:
        d = detail_by_key.get(ik)
        out.append(
            _Candidate(
                ind_key=ik,
                symbol=(d.symbol if d and d.symbol else None) or ik,
                name=(d.name if d and d.name else lk_names.get(ik)),
                sector=None,  # details carry no sector; movers do
                price=d.live_price if d else None,
                change_pct=d.day_change_percentage if d else None,
                source="lookup",
            )
        )
    return out


async def scanner(state: PortfolioState) -> PortfolioState:
    """Populate ``state.scan_results`` from the user's query.

    If the query names explicit stocks, return ONLY those (no movers padding);
    otherwise scan market movers for the intent's categories.
    """
    intent = await _intent(state.user_query)

    candidates: List[_Candidate] = []
    if intent.symbols:
        candidates = await _from_symbols(intent.symbols)

    named = bool(candidates)
    if not candidates:
        # No named stocks (or none resolved) -> momentum scan.
        cats = intent.categories or ["top-gainers"]
        groups = await asyncio.gather(*(_from_movers(c) for c in cats), return_exceptions=True)
        movers = [c for g in groups if isinstance(g, list) for c in g]
        movers.sort(key=lambda c: abs(c.change_pct or 0.0), reverse=True)
        candidates = movers

    cap = min(len(candidates), _MAX_NAMED) if named else MAX_OPPORTUNITIES

    results: List[ScanResult] = []
    seen = set()
    for c in candidates:
        key = c.ind_key or c.symbol
        if key in seen:
            continue
        seen.add(key)
        change = c.change_pct or 0.0
        results.append(
            ScanResult(
                symbol=c.symbol,
                ind_key=c.ind_key,
                name=c.name,
                sector=c.sector,
                signal=(
                    "named in query"
                    if c.source == "lookup"
                    else f"{change:+.2f}% — {c.source.split(':')[-1]}"
                ),
                last_price=c.price,
                change_percent=c.change_pct,
                score=max(0.0, min(1.0, abs(change) / 10.0)),
                source=c.source,
            )
        )
        if len(results) >= cap:
            break

    state.scan_results = results
    return state
