"""RiskManager agent — enforces guardrails on analyst recommendations.

Pure async node ``(state: PortfolioState) -> PortfolioState``. Guardrail
enforcement is deterministic (correctness must not depend on the LLM):

- Min confidence to proceed: 0.70
- Max stocks per sector: 3
- Analyst 'avoid' recommendations are rejected

Each recommendation yields a ``RiskAssessment`` with a PASS / REJECT / FLAG
decision. ``llama-3.3-70b-versatile`` is used only to attach human-readable risk
notes. If every candidate is rejected, ``state.rejection_reason`` is set.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from graph.state import (
    AnalystRecommendation,
    PortfolioState,
    RiskAssessment,
)

RISK_MODEL = "llama-3.3-70b-versatile"
MIN_CONFIDENCE = 0.70
MAX_PER_SECTOR = 3
_FLAG_BAND = 0.75  # passes guardrails but flagged for review when below this


class _RiskNote(BaseModel):
    symbol: str
    note: str


class _RiskNotes(BaseModel):
    notes: List[_RiskNote] = Field(default_factory=list)


def _sector_map(state: PortfolioState) -> Dict[str, Optional[str]]:
    return {s.symbol: s.sector for s in state.scan_results}


def _assess(
    rec: AnalystRecommendation,
    sector: Optional[str],
    sector_counts: Dict[str, int],
) -> RiskAssessment:
    violations: List[str] = []
    if rec.confidence < MIN_CONFIDENCE:
        violations.append("confidence_below_threshold")
    if rec.action == "avoid":
        violations.append("analyst_recommends_avoid")

    # Sector cap only applies to known sectors. Named-stock lookups carry no
    # sector, so they are never blocked by (or counted toward) the cap.
    if not violations and sector and sector_counts.get(sector, 0) >= MAX_PER_SECTOR:
        violations.append("sector_limit_exceeded")

    approved = not violations
    if approved:
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        decision = "FLAG" if rec.confidence < _FLAG_BAND else "PASS"
    else:
        decision = "REJECT"

    return RiskAssessment(
        symbol=rec.symbol,
        sector=sector,
        approved=approved,
        decision=decision,
        confidence=rec.confidence,
        violations=violations,
    )


async def _annotate(
    assessments: List[RiskAssessment],
    recs_by_symbol: Dict[str, AnalystRecommendation],
) -> List[RiskAssessment]:
    """Attach one-line LLM risk notes (best-effort; deterministic verdicts unchanged)."""
    if not assessments:
        return assessments
    lines = [
        "You are a risk manager for an equity research desk.",
        "For each assessment write a one-line note explaining the verdict.",
        f"Guardrails: min confidence {MIN_CONFIDENCE}, max {MAX_PER_SECTOR} stocks per sector.",
        "",
        "Assessments:",
    ]
    for a in assessments:
        rec = recs_by_symbol.get(a.symbol)
        lines.append(
            f"- {a.symbol} sector={a.sector} decision={a.decision} "
            f"confidence={a.confidence} violations={a.violations} "
            f"action={getattr(rec, 'action', None)}"
        )
    try:
        llm = ChatGroq(model=RISK_MODEL, temperature=0).with_structured_output(_RiskNotes)
        out = await llm.ainvoke("\n".join(lines))
        note_map = {n.symbol: n.note for n in out.notes}
        for a in assessments:
            if a.symbol in note_map:
                a.notes = note_map[a.symbol]
    except Exception:  # noqa: BLE001 - notes are optional
        pass
    return assessments


def _summarize_rejection(assessments: List[RiskAssessment]) -> str:
    reasons = sorted({v for a in assessments for v in a.violations})
    symbols = ", ".join(a.symbol for a in assessments)
    return (
        f"All {len(assessments)} candidate(s) rejected ({symbols}). "
        f"Violations: {', '.join(reasons) or 'n/a'}."
    )


async def risk_manager(state: PortfolioState) -> PortfolioState:
    """Populate ``state.risk_assessments`` and ``state.rejection_reason`` if all fail."""
    sectors = _sector_map(state)
    # Highest-confidence first so the sector cap keeps the strongest names.
    ordered = sorted(
        state.analyst_recommendations, key=lambda r: r.confidence, reverse=True
    )
    sector_counts: Dict[str, int] = {}
    assessments = [_assess(rec, sectors.get(rec.symbol), sector_counts) for rec in ordered]

    assessments = await _annotate(assessments, {r.symbol: r for r in ordered})
    state.risk_assessments = assessments

    if assessments and all(not a.approved for a in assessments):
        state.rejection_reason = _summarize_rejection(assessments)
    return state
