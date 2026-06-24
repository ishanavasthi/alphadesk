"""Research agent — deep dive per scan candidate.

Pure async node ``(state: PortfolioState) -> PortfolioState``. For each item in
``state.scan_results`` it gathers details, the option chain, and greeks history
concurrently, compiles typed fundamentals/options insight, and writes a
``ResearchReport`` into ``state.research_reports`` keyed by symbol.

Uses ``llama-3.1-8b-instant`` for a lightweight factual summary; the heavy
synthesis (bull/bear thesis) is the Analyst agent's job.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional

from langchain_groq import ChatGroq

from graph.state import PortfolioState, ResearchReport, ScanResult
from tools.ind_money import (
    GreeksHistoryResponse,
    OptionChainResponse,
    StockDetails,
    get_indian_stocks_details,
    get_indian_stocks_greeks_history,
    get_indian_stocks_option_chain,
)

RESEARCH_MODEL = "llama-3.1-8b-instant"

_FUNDAMENTAL_FIELDS = (
    "last_price",
    "market_cap",
    "pe_ratio",
    "day_high",
    "day_low",
    "week52_high",
    "week52_low",
)


def _get_llm() -> ChatGroq:
    return ChatGroq(model=RESEARCH_MODEL, temperature=0)


def _fundamentals(details: object) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if isinstance(details, StockDetails):
        for key in _FUNDAMENTAL_FIELDS:
            value = getattr(details, key, None)
            if isinstance(value, (int, float)):
                out[key] = float(value)
    return out


def _summarize_options(chain: object, greeks: object) -> Optional[str]:
    parts = []
    if isinstance(chain, OptionChainResponse) and chain.strikes:
        note = f"{len(chain.strikes)} strikes in chain"
        if chain.underlying_price is not None:
            note += f", underlying {chain.underlying_price}"
        parts.append(note)
    if isinstance(greeks, GreeksHistoryResponse) and greeks.snapshots:
        last = greeks.snapshots[-1]
        if last.iv is not None:
            parts.append(f"latest IV {last.iv}")
    return "; ".join(parts) or None


async def _summarize(
    item: ScanResult,
    details: object,
    fundamentals: Dict[str, float],
    options_insight: Optional[str],
) -> str:
    facts = [f"Symbol: {item.symbol}", f"Signal: {item.signal}"]
    if isinstance(details, StockDetails):
        if details.name:
            facts.append(f"Name: {details.name}")
        if details.sector:
            facts.append(f"Sector: {details.sector}")
    if fundamentals:
        facts.append("Fundamentals: " + ", ".join(f"{k}={v}" for k, v in fundamentals.items()))
    if options_insight:
        facts.append(f"Options: {options_insight}")

    prompt = (
        "Summarize the following NSE stock research in 2-3 factual sentences "
        "for an analyst. Do not give a recommendation.\n\n" + "\n".join(facts)
    )
    try:
        msg = await _get_llm().ainvoke(prompt)
        return getattr(msg, "content", None) or "\n".join(facts)
    except Exception:  # noqa: BLE001 - fall back to the raw fact sheet
        return "\n".join(facts)


async def _research_one(item: ScanResult) -> ResearchReport:
    details, chain, greeks = await asyncio.gather(
        get_indian_stocks_details.ainvoke({"symbol": item.symbol}),
        get_indian_stocks_option_chain.ainvoke({"symbol": item.symbol}),
        get_indian_stocks_greeks_history.ainvoke({"symbol": item.symbol}),
        return_exceptions=True,
    )

    sources = []
    if isinstance(details, StockDetails):
        sources.append("get_indian_stocks_details")
    if isinstance(chain, OptionChainResponse):
        sources.append("get_indian_stocks_option_chain")
    if isinstance(greeks, GreeksHistoryResponse):
        sources.append("get_indian_stocks_greeks_history")

    fundamentals = _fundamentals(details)
    options_insight = _summarize_options(chain, greeks)
    summary = await _summarize(item, details, fundamentals, options_insight)

    return ResearchReport(
        symbol=item.symbol,
        summary=summary,
        fundamentals=fundamentals,
        technicals={},
        options_insight=options_insight,
        sources=sources,
    )


async def research(state: PortfolioState) -> PortfolioState:
    """Populate ``state.research_reports`` (keyed by symbol) for every scan result."""
    if not state.scan_results:
        return state
    reports = await asyncio.gather(
        *(_research_one(item) for item in state.scan_results), return_exceptions=True
    )
    for report in reports:
        if isinstance(report, ResearchReport):
            state.research_reports[report.symbol] = report
    return state
