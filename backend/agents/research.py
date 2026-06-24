"""Research agent — deep dive per scan candidate (keyed by ind_key).

Pure async node ``(state: PortfolioState) -> PortfolioState``. For each scan
result it fetches details (and, for F&O names, the option chain + greeks),
compiles typed fundamentals, and writes a ``ResearchReport`` into
``state.research_reports`` keyed by symbol.

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
    StockDetail,
    StockDetailsResponse,
    get_indian_stocks_details,
    get_indian_stocks_greeks_history,
    get_indian_stocks_option_chain,
)

RESEARCH_MODEL = "llama-3.1-8b-instant"


def _get_llm() -> ChatGroq:
    return ChatGroq(model=RESEARCH_MODEL, temperature=0)


def _fundamentals(detail: Optional[StockDetail]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not detail:
        return out
    mapping = {
        "live_price": detail.live_price,
        "day_change_percentage": detail.day_change_percentage,
        "market_cap_cr": detail.market_cap_in_currency,
        "week52_high": detail.week52_high,
        "week52_low": detail.week52_low,
    }
    for key, value in mapping.items():
        if isinstance(value, (int, float)):
            out[key] = float(value)
    return out


def _options_insight(chain: object, greeks: object) -> Optional[str]:
    parts = []
    if isinstance(chain, OptionChainResponse) and chain.strikes:
        note = f"{len(chain.strikes)} strikes"
        if chain.expiry_date:
            note += f" (expiry {chain.expiry_date})"
        parts.append(note)
    if isinstance(greeks, GreeksHistoryResponse) and greeks.snapshots:
        parts.append(f"{len(greeks.snapshots)} greeks snapshots")
    return "; ".join(parts) or None


async def _summarize(
    item: ScanResult,
    detail: Optional[StockDetail],
    fundamentals: Dict[str, float],
    options_insight: Optional[str],
) -> str:
    facts = [f"Symbol: {item.symbol}", f"Signal: {item.signal}"]
    if detail and detail.name:
        facts.append(f"Name: {detail.name}")
    if item.sector:
        facts.append(f"Sector: {item.sector}")
    if detail and detail.market_cap:
        facts.append(f"Market cap band: {detail.market_cap}")
    if fundamentals:
        facts.append("Fundamentals: " + ", ".join(f"{k}={v}" for k, v in fundamentals.items()))
    if options_insight:
        facts.append(f"Options: {options_insight}")

    prompt = (
        "Summarize the following NSE stock research in 2-3 factual sentences for an "
        "analyst. Do not give a recommendation.\n\n" + "\n".join(facts)
    )
    try:
        msg = await _get_llm().ainvoke(prompt)
        return getattr(msg, "content", None) or "\n".join(facts)
    except Exception:  # noqa: BLE001
        return "\n".join(facts)


async def _research_one(item: ScanResult) -> ResearchReport:
    sources = []
    detail: Optional[StockDetail] = None

    if item.ind_key:
        details_res = await get_indian_stocks_details.ainvoke(
            {"ind_keys": [item.ind_key], "segments": ["analyst", "news"]}
        )
        if isinstance(details_res, StockDetailsResponse):
            detail = details_res.details.get(item.ind_key) or next(
                iter(details_res.details.values()), None
            )
            if detail:
                sources.append("get_indian_stocks_details")

    fundamentals = _fundamentals(detail)

    # Option chain / greeks only make sense for F&O underlyings.
    chain = greeks = None
    if item.ind_key and detail and detail.has_fno:
        chain, greeks = await asyncio.gather(
            get_indian_stocks_option_chain.ainvoke(
                {"ind_key": item.ind_key, "use_expiry_date": False}
            ),
            get_indian_stocks_greeks_history.ainvoke({"ind_key": item.ind_key}),
            return_exceptions=True,
        )
        if isinstance(chain, OptionChainResponse):
            sources.append("get_indian_stocks_option_chain")
        if isinstance(greeks, GreeksHistoryResponse):
            sources.append("get_indian_stocks_greeks_history")

    options_insight = _options_insight(chain, greeks)
    summary = await _summarize(item, detail, fundamentals, options_insight)

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
