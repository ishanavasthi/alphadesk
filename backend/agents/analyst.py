"""Analyst agent — synthesizes research into structured recommendations.

Pure async node ``(state: PortfolioState) -> PortfolioState``. For each
``ResearchReport`` it gathers RAG context (``rag.retriever``) plus IND key
references (``lookup_ind_keys``), then uses ``llama-3.3-70b-versatile`` to
produce an ``AnalystRecommendation`` (bull/bear thesis, price target, confidence,
key risks, catalysts) written into ``state.analyst_recommendations``.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from graph.state import AnalystRecommendation, PortfolioState, ResearchReport
from rag.retriever import get_relevant_context

ANALYST_MODEL = "llama-3.3-70b-versatile"


class _AnalystOutput(BaseModel):
    """Structured LLM output mapped onto AnalystRecommendation."""

    action: Literal["buy", "hold", "avoid"] = Field(..., description="Recommended stance.")
    bull_thesis: str = Field(..., description="The case for the stock outperforming.")
    bear_thesis: str = Field(..., description="The downside case.")
    target_price: Optional[float] = Field(None, description="Optional price target.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence 0-1.")
    key_risks: List[str] = Field(default_factory=list, description="Principal risks.")
    catalysts: List[str] = Field(default_factory=list, description="Catalysts.")
    thesis: Optional[str] = Field(None, description="One-paragraph overall synthesis.")


def _get_llm() -> ChatGroq:
    return ChatGroq(model=ANALYST_MODEL, temperature=0)


def _gather_context(report: ResearchReport) -> List[str]:
    """RAG passages relevant to the symbol + research summary."""
    return get_relevant_context(report.symbol, report.summary)


def _build_prompt(report: ResearchReport, context: List[str]) -> str:
    lines = [
        "You are an equity analyst covering NSE stocks.",
        "Using the research and reference context below, produce a structured view:",
        "bull thesis, bear thesis, price target, confidence (0-1), key risks, catalysts,",
        "and an action of buy/hold/avoid.",
        "",
        f"Symbol: {report.symbol}",
        f"Research summary: {report.summary}",
    ]
    if report.fundamentals:
        lines.append(
            "Fundamentals: " + ", ".join(f"{k}={v}" for k, v in report.fundamentals.items())
        )
    if report.options_insight:
        lines.append(f"Options: {report.options_insight}")
    if context:
        lines.append("Reference context:")
        lines.extend(f"- {c}" for c in context)
    return "\n".join(lines)


async def _analyze_one(report: ResearchReport) -> Optional[AnalystRecommendation]:
    context = _gather_context(report)
    try:
        llm = _get_llm().with_structured_output(_AnalystOutput)
        out = await llm.ainvoke(_build_prompt(report, context))
    except Exception:  # noqa: BLE001 - skip stocks the model can't score
        return None

    return AnalystRecommendation(
        symbol=report.symbol,
        action=out.action,
        confidence=out.confidence,
        thesis=out.thesis,
        bull_thesis=out.bull_thesis,
        bear_thesis=out.bear_thesis,
        key_risks=out.key_risks,
        catalysts=out.catalysts,
        target_price=out.target_price,
        citations=context,
    )


async def analyst(state: PortfolioState) -> PortfolioState:
    """Populate ``state.analyst_recommendations`` from the research reports."""
    recommendations: List[AnalystRecommendation] = []
    for report in state.research_reports.values():
        rec = await _analyze_one(report)
        if rec is not None:
            recommendations.append(rec)
    state.analyst_recommendations = recommendations
    return state
