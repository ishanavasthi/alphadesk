"""Analyst agent — synthesizes research into structured recommendations.

Pure async node ``(state: PortfolioState) -> PortfolioState``. For each
``ResearchReport`` it gathers RAG context (``rag.retriever``) plus IND key
references (``lookup_ind_keys``), then uses ``openai/gpt-oss-120b`` to
produce an ``AnalystRecommendation`` (bull/bear thesis, price target, confidence,
key risks, catalysts) written into ``state.analyst_recommendations``.
"""

from __future__ import annotations

import logging
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from agents.llm import get_lab_llm, structured
from graph.state import AnalystRecommendation, PortfolioState, ResearchReport
from rag.retriever import get_relevant_context

# NOTE: the ``openai/`` prefix is part of the *Groq* model id (GPT OSS 120B
# served by Groq) — the default route is Groq, not OpenAI. Override the tier
# with LAB_ANALYST_MODEL / LAB_MODEL and the route with LAB_PROVIDER.
ANALYST_MODEL = "openai/gpt-oss-120b"

logger = logging.getLogger("alphadesk.analyst")


class _AnalystOutput(BaseModel):
    """Structured LLM output mapped onto AnalystRecommendation.

    **Field order is deliberate (B11).** The model fills a function-call argument
    object left to right, so the reasoning fields come *before* ``action`` and
    ``confidence``: the model states both theses, names the risks and gaps, and
    only then commits to a stance and a number. The previous order put ``action``
    first, so the model picked buy/hold/avoid and then produced a confidence that
    rationalised a decision already made.

    ``evidence_quality`` and ``data_gaps`` are optional with defaults on purpose:
    a weaker Lab model that omits them must still parse, not raise and get the
    whole stock silently dropped (the ``_analyze_one`` skip). See B11 phase 2.
    """

    bull_thesis: str = Field(..., description="The case for the stock outperforming.")
    bear_thesis: str = Field(..., description="The downside case.")
    key_risks: List[str] = Field(default_factory=list, description="Principal risks.")
    catalysts: List[str] = Field(default_factory=list, description="Catalysts.")
    data_gaps: List[str] = Field(
        default_factory=list,
        description="What you would need to be more sure (e.g. earnings, valuation, filings).",
    )
    target_price: Optional[float] = Field(None, description="Optional price target.")
    time_horizon: Optional[str] = Field(
        None, description="Intended holding horizon, e.g. 'short-term', '6-12 months'."
    )
    action: Literal["buy", "hold", "avoid"] = Field(..., description="Recommended stance.")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Probability the action is directionally right over the horizon "
            "(for 'buy', that it outperforms NIFTY 50). 0.50 = coin flip, "
            "0.70 = a clear view you would act on, 0.85+ = strong and corroborated."
        ),
    )
    evidence_quality: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "How much the view rests on real data vs. inference. You have only "
            "price and 52-week-range data here, so be honest that this is low."
        ),
    )
    thesis: Optional[str] = Field(None, description="One-paragraph overall synthesis.")


def _get_llm():
    return get_lab_llm("analyst", ANALYST_MODEL, temperature=0)


def _gather_context(report: ResearchReport) -> List[str]:
    """RAG passages relevant to the symbol + research summary."""
    return get_relevant_context(report.symbol, report.summary)


def _build_prompt(report: ResearchReport, context: List[str]) -> str:
    lines = [
        "You are an equity analyst covering NSE stocks.",
        "Work in this order: first write the bull and bear theses, name the key",
        "risks, catalysts and the data you are missing; only then choose an action",
        "of buy/hold/avoid and score your conviction.",
        "",
        "Two separate numbers, both in [0, 1]:",
        "- confidence = your probability that the action is directionally right over",
        "  the horizon (for 'buy', that the stock outperforms NIFTY 50). 0.50 is a",
        "  coin flip, 0.70 a clear view you would act on, 0.85+ strong and corroborated.",
        "  Score the strength of the view itself — do NOT discount it here for thin data.",
        "- evidence_quality = how much that view rests on real data rather than",
        "  inference. You are given only live price and the 52-week range — no",
        "  earnings, valuation, order book or filings — so evidence_quality is",
        "  inherently low here; say so honestly and list what is missing in data_gaps.",
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
        llm = structured(_get_llm(), _AnalystOutput)
        out = await llm.ainvoke(_build_prompt(report, context))
    except Exception as exc:  # noqa: BLE001 - skip stocks the model can't score
        # A silent drop here is the exact failure `structured()` was written to
        # prevent: every candidate vanishes and the run comes back empty with
        # nothing logged. Skip the stock, but never silently (B11).
        logger.warning("analyst skipped %s: %s", report.symbol, exc)
        return None

    return AnalystRecommendation(
        symbol=report.symbol,
        action=out.action,
        confidence=out.confidence,
        evidence_quality=out.evidence_quality,
        data_gaps=out.data_gaps,
        thesis=out.thesis,
        bull_thesis=out.bull_thesis,
        bear_thesis=out.bear_thesis,
        key_risks=out.key_risks,
        catalysts=out.catalysts,
        target_price=out.target_price,
        time_horizon=out.time_horizon,
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
