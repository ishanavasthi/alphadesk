"""Scanner agent — screens NSE stocks for tradable signals.

Pure async node ``(state: PortfolioState) -> PortfolioState``. Pulls market
movers, confirms momentum with OHLC, then uses ``llama-3.1-8b-instant`` to rank
the field down to the top 5 opportunities written into ``state.scan_results``.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from graph.state import PortfolioState, ScanResult
from tools.ind_money import (
    MoversResponse,
    OHLCResponse,
    get_indian_stocks_movers,
    get_indian_stocks_ohlc,
)

SCANNER_MODEL = "llama-3.1-8b-instant"
MAX_OPPORTUNITIES = 5
_OHLC_ENRICH_LIMIT = 10  # cap OHLC calls to bound latency/cost


def _get_llm() -> ChatGroq:
    return ChatGroq(model=SCANNER_MODEL, temperature=0)


class _Candidate(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    last_price: Optional[float] = None
    change_percent: Optional[float] = None
    source: str
    momentum: Optional[float] = None  # close-vs-close over the OHLC window, percent


class _ScannerPick(BaseModel):
    symbol: str = Field(..., description="Ticker chosen as an opportunity.")
    signal: str = Field(..., description="One-line reason this stock is interesting.")
    score: float = Field(..., ge=0.0, le=1.0, description="Relative signal strength 0-1.")


class _ScannerPicks(BaseModel):
    picks: List[_ScannerPick] = Field(default_factory=list)


def _collect_candidates(movers: MoversResponse) -> List[_Candidate]:
    """Flatten gainers/most-active/losers into a de-duplicated candidate list."""
    out: List[_Candidate] = []
    seen: set[str] = set()
    buckets = (
        ("get_indian_stocks_movers:gainers", movers.gainers),
        ("get_indian_stocks_movers:most_active", movers.most_active),
        ("get_indian_stocks_movers:losers", movers.losers),
    )
    for source, items in buckets:
        for it in items:
            if not it.symbol or it.symbol in seen:
                continue
            seen.add(it.symbol)
            out.append(
                _Candidate(
                    symbol=it.symbol,
                    name=it.name,
                    last_price=it.last_price,
                    change_percent=it.change_percent,
                    source=source,
                )
            )
    return out


async def _enrich_momentum(cand: _Candidate) -> _Candidate:
    """Attach a 1-month close-vs-close momentum reading from OHLC, if available."""
    res = await get_indian_stocks_ohlc.ainvoke(
        {"symbol": cand.symbol, "interval": "1d", "range": "1mo"}
    )
    if isinstance(res, OHLCResponse) and res.bars:
        first, last = res.bars[0].close, res.bars[-1].close
        if first and last:
            cand.momentum = round((last - first) / first * 100.0, 2)
    return cand


def _build_rank_prompt(candidates: List[_Candidate]) -> str:
    lines = [
        "You are a market scanner for NSE equities.",
        f"From the candidates below, select the top {MAX_OPPORTUNITIES} trading opportunities.",
        "Score each 0-1 by signal strength and give a one-line signal reason.",
        "",
        "Candidates:",
    ]
    for c in candidates:
        lines.append(
            f"- {c.symbol} ({c.name or 'n/a'}): price={c.last_price}, "
            f"day_change={c.change_percent}%, 1mo_momentum={c.momentum}%, source={c.source}"
        )
    return "\n".join(lines)


def _heuristic_rank(candidates: List[_Candidate]) -> List[_ScannerPick]:
    """Fallback ranking by absolute daily move when the LLM is unavailable."""
    ranked = sorted(candidates, key=lambda c: abs(c.change_percent or 0.0), reverse=True)
    picks: List[_ScannerPick] = []
    for c in ranked[:MAX_OPPORTUNITIES]:
        score = max(0.0, min(1.0, abs(c.change_percent or 0.0) / 10.0))
        picks.append(
            _ScannerPick(
                symbol=c.symbol,
                signal=f"{c.change_percent or 0:+.2f}% move via {c.source.split(':')[-1]}",
                score=score,
            )
        )
    return picks


async def _rank_candidates(candidates: List[_Candidate]) -> List[_ScannerPick]:
    try:
        llm = _get_llm().with_structured_output(_ScannerPicks)
        out = await llm.ainvoke(_build_rank_prompt(candidates))
        if out and out.picks:
            return out.picks
    except Exception:  # noqa: BLE001 - degrade to heuristic ranking
        pass
    return _heuristic_rank(candidates)


async def scanner(state: PortfolioState) -> PortfolioState:
    """Populate ``state.scan_results`` with the top opportunities found on NSE."""
    movers = await get_indian_stocks_movers.ainvoke({"category": None})
    if isinstance(movers, str):  # MCP error string — nothing to scan
        state.scan_results = []
        return state

    candidates = _collect_candidates(movers)
    if not candidates:
        state.scan_results = []
        return state

    head = candidates[:_OHLC_ENRICH_LIMIT]
    enriched = await asyncio.gather(
        *(_enrich_momentum(c) for c in head), return_exceptions=True
    )
    for i, r in enumerate(enriched):
        if isinstance(r, _Candidate):
            head[i] = r
    candidates[:_OHLC_ENRICH_LIMIT] = head

    picks = await _rank_candidates(candidates)
    by_symbol = {c.symbol: c for c in candidates}

    results: List[ScanResult] = []
    for p in picks[:MAX_OPPORTUNITIES]:
        c = by_symbol.get(p.symbol)
        results.append(
            ScanResult(
                symbol=p.symbol,
                name=c.name if c else None,
                sector=c.sector if c else None,
                signal=p.signal,
                last_price=c.last_price if c else None,
                change_percent=c.change_percent if c else None,
                score=p.score,
                source=c.source if c else "scanner",
            )
        )
    state.scan_results = results
    return state
