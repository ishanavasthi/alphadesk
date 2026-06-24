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
MAX_OPPORTUNITIES = 5
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


async def _from_symbols(symbols: List[str]) -> List[_Candidate]:
    lookup = await lookup_ind_keys.ainvoke({"names": symbols})
    if not isinstance(lookup, IndKeysResponse) or not lookup.keys:
        return []
    ind_keys = [k.ind_key for k in lookup.keys if k.ind_key]
    if not ind_keys:
        return []
    details = await get_indian_stocks_details.ainvoke(
        {"ind_keys": ind_keys[:10], "segments": None}
    )
    by_symbol: Dict[str, _Candidate] = {}
    if isinstance(details, StockDetailsResponse):
        for d in details.details.values():
            if not d.symbol:
                continue
            by_symbol[d.symbol.upper()] = _Candidate(
                ind_key=d.ind_key,
                symbol=d.symbol,
                name=d.name,
                sector=None,
                price=d.live_price,
                change_pct=d.day_change_percentage,
                source="lookup",
            )
    # Prefer exact ticker matches; fall back to whatever resolved.
    out: List[_Candidate] = []
    seen = set()
    for sym in symbols:
        cand = by_symbol.get(sym.upper())
        if cand and cand.ind_key not in seen:
            out.append(cand)
            seen.add(cand.ind_key)
    if not out:
        out = list(by_symbol.values())
    return out


async def scanner(state: PortfolioState) -> PortfolioState:
    """Populate ``state.scan_results`` from the user's query."""
    intent = await _intent(state.user_query)

    tasks = [_from_movers(c) for c in intent.categories]
    if intent.symbols:
        tasks.append(_from_symbols(intent.symbols))
    groups = await asyncio.gather(*tasks, return_exceptions=True)

    # Symbol matches first (explicitly requested), then movers.
    symbol_cands: List[_Candidate] = []
    mover_cands: List[_Candidate] = []
    for g in groups:
        if not isinstance(g, list):
            continue
        for c in g:
            (symbol_cands if c.source == "lookup" else mover_cands).append(c)

    mover_cands.sort(key=lambda c: abs(c.change_pct or 0.0), reverse=True)

    results: List[ScanResult] = []
    seen = set()
    for c in symbol_cands + mover_cands:
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
        if len(results) >= MAX_OPPORTUNITIES:
            break

    state.scan_results = results
    return state
