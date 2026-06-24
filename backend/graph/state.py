"""Shared graph state for AlphaDesk.

Defines ``PortfolioState`` — the single Pydantic model that flows through every
node of the LangGraph — together with all nested models the agents read from and
write to. Each agent is a pure function ``(state: PortfolioState) -> PortfolioState``
that accretes its output onto the state.

Field semantics tie back to the guardrails in CLAUDE.md: analyst confidence must
reach 0.70 to proceed, no more than 3 stocks per sector, and any watchlist write
requires ``human_approved`` to be True.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Scanner output
# --------------------------------------------------------------------------- #
class ScanResult(BaseModel):
    """A single candidate surfaced by the Scanner agent."""

    symbol: str = Field(..., description="NSE ticker symbol, e.g. 'RELIANCE'.")
    name: Optional[str] = Field(None, description="Company display name, if known.")
    sector: Optional[str] = Field(
        None, description="Sector classification used by the per-sector guardrail."
    )
    signal: str = Field(
        ..., description="Why this stock was flagged, e.g. 'top gainer', 'volume spike'."
    )
    last_price: Optional[float] = Field(None, description="Latest traded price at scan time.")
    change_percent: Optional[float] = Field(
        None, description="Percent move that triggered the signal."
    )
    score: Optional[float] = Field(
        None, description="Scanner-assigned interest score (higher = stronger signal)."
    )
    source: Optional[str] = Field(
        None, description="IND Money tool the signal came from, e.g. 'get_indian_stocks_movers'."
    )


# --------------------------------------------------------------------------- #
# Research output
# --------------------------------------------------------------------------- #
class ResearchReport(BaseModel):
    """Deep-dive findings produced by the Research agent for one candidate."""

    symbol: str = Field(..., description="NSE ticker the report covers.")
    summary: str = Field(..., description="Narrative summary of the research findings.")
    fundamentals: Dict[str, float] = Field(
        default_factory=dict,
        description="Key fundamental metrics, e.g. {'pe_ratio': 22.4, 'market_cap': 1.2e12}.",
    )
    technicals: Dict[str, float] = Field(
        default_factory=dict,
        description="Key technical metrics derived from OHLC, e.g. {'rsi': 61.0}.",
    )
    options_insight: Optional[str] = Field(
        None,
        description="Notes from option chain / greeks history (IV, OI skew, etc.), if analyzed.",
    )
    sources: List[str] = Field(
        default_factory=list,
        description="IND Money tools or documents consulted to build the report.",
    )


# --------------------------------------------------------------------------- #
# Analyst output
# --------------------------------------------------------------------------- #
class AnalystRecommendation(BaseModel):
    """Structured recommendation written by the Analyst agent."""

    symbol: str = Field(..., description="NSE ticker the recommendation applies to.")
    action: Literal["buy", "hold", "avoid"] = Field(
        ..., description="Recommended stance on the stock."
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score in [0, 1]; must reach 0.70 to clear the RiskManager.",
    )
    thesis: str = Field(..., description="Investment thesis supporting the recommended action.")
    target_price: Optional[float] = Field(
        None, description="Optional price target underpinning the thesis."
    )
    time_horizon: Optional[str] = Field(
        None, description="Intended holding horizon, e.g. 'short-term', '6-12 months'."
    )
    citations: List[str] = Field(
        default_factory=list,
        description="RAG passages or ind_keys references backing the thesis.",
    )


# --------------------------------------------------------------------------- #
# Risk output
# --------------------------------------------------------------------------- #
class RiskAssessment(BaseModel):
    """RiskManager verdict on a single recommendation (pure logic on state)."""

    symbol: str = Field(..., description="NSE ticker being assessed.")
    sector: Optional[str] = Field(
        None, description="Sector used to enforce the max-3-stocks-per-sector rule."
    )
    approved: bool = Field(
        ..., description="True if the recommendation passes all guardrails."
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence carried over from the recommendation (checked against 0.70).",
    )
    violations: List[str] = Field(
        default_factory=list,
        description="Guardrails breached, e.g. ['confidence_below_threshold', 'sector_limit'].",
    )
    notes: Optional[str] = Field(
        None, description="Human-readable explanation of the verdict."
    )


# --------------------------------------------------------------------------- #
# Execution input
# --------------------------------------------------------------------------- #
class PendingAction(BaseModel):
    """An action awaiting the human-in-the-loop gate before the Execution agent runs it."""

    action_type: Literal["add_to_watchlist", "place_order"] = Field(
        ..., description="What the Execution agent will do once approved."
    )
    symbol: str = Field(..., description="NSE ticker the action targets.")
    rationale: Optional[str] = Field(
        None, description="Why this action is being proposed (links back to the thesis)."
    )
    payload: Dict[str, object] = Field(
        default_factory=dict,
        description="Action parameters, e.g. {'quantity': 10} for a future order.",
    )
    requires_human: bool = Field(
        True, description="Whether explicit human approval is required before execution."
    )
    status: Literal["pending", "approved", "rejected", "executed"] = Field(
        "pending", description="Lifecycle status of the action."
    )


# --------------------------------------------------------------------------- #
# Top-level graph state
# --------------------------------------------------------------------------- #
class PortfolioState(BaseModel):
    """Single shared state object threaded through every node of the LangGraph."""

    user_query: str = Field(
        ..., description="Natural-language research request that kicked off the run."
    )
    scan_results: List[ScanResult] = Field(
        default_factory=list, description="Candidates surfaced by the Scanner agent."
    )
    research_reports: Dict[str, ResearchReport] = Field(
        default_factory=dict,
        description="Research reports keyed by NSE symbol.",
    )
    analyst_recommendations: List[AnalystRecommendation] = Field(
        default_factory=list, description="Structured recommendations from the Analyst agent."
    )
    risk_assessments: List[RiskAssessment] = Field(
        default_factory=list, description="RiskManager verdicts on the recommendations."
    )
    pending_actions: List[PendingAction] = Field(
        default_factory=list,
        description="Actions queued for the human-in-the-loop gate / Execution agent.",
    )
    approved_actions: List[PendingAction] = Field(
        default_factory=list,
        description=(
            "Actions promoted from pending_actions after human_approved=True. "
            "When no broker is configured, they stop here (no live order is placed)."
        ),
    )
    execution_history: List[PendingAction] = Field(
        default_factory=list,
        description="Audit trail of actions the Execution agent has processed (executed or persisted).",
    )
    paper_watchlist: List[str] = Field(
        default_factory=list,
        description=(
            "Application-level watchlist of NSE symbols that passed research and risk checks. "
            "Not connected to any brokerage; the read-only IND Money MCP cannot modify real watchlists."
        ),
    )
    human_approved: bool = Field(
        False,
        description="Set True by the human gate; required before any user_watchlist write.",
    )
    rejection_reason: Optional[str] = Field(
        None, description="Reason supplied by the human when approval is withheld."
    )
