"""Execution agent — paper watchlist + human-in-the-loop gate.

IMPORTANT: the IND Money MCP is READ-ONLY. This agent never calls
``user_watchlist`` or otherwise mutates the user's real IND Money watchlists.
Instead it maintains an application-level paper watchlist and an approval queue.

The graph gates this node with ``interrupt_before=["execution"]`` (see
graph/graph.py), so the human-in-the-loop pause happens *before* this node runs.
When it runs it:

1. Stages PASS stocks as PendingActions, adding them to ``paper_watchlist``.
2. If ``human_approved`` is True, places a real order for each action when a
   BrokerAdapter is configured, otherwise logs and persists; then moves actions
   from ``pending_actions`` to ``approved_actions`` (paper_watchlist preserved).

No real trade is ever placed unless a BrokerAdapter is explicitly configured.
"""

from __future__ import annotations

import logging

from broker.base import load_broker
from graph.state import PendingAction, PortfolioState

logger = logging.getLogger("alphadesk.execution")

_NO_BROKER_MSG = "Broker integration not configured. Action saved for future execution."


def _stage_pending(state: PortfolioState) -> PortfolioState:
    """Phase 1: queue PASS stocks for approval and add them to the paper watchlist."""
    existing = {pa.symbol for pa in state.pending_actions}
    for assessment in state.risk_assessments:
        if assessment.decision != "PASS" or assessment.symbol in existing:
            continue
        state.pending_actions.append(
            PendingAction(
                action_type="add_to_watchlist",
                symbol=assessment.symbol,
                rationale=assessment.notes
                or f"Passed risk checks (confidence={assessment.confidence:.2f}).",
                requires_human=True,
                status="pending",
            )
        )
        existing.add(assessment.symbol)
        if assessment.symbol not in state.paper_watchlist:
            state.paper_watchlist.append(assessment.symbol)
    return state


def _process_approved(state: PortfolioState) -> PortfolioState:
    """Phase 2: human approved -> place orders if a broker exists, else persist."""
    broker = load_broker()
    for action in state.pending_actions:
        if broker is not None:
            try:
                broker.place_order(action)
                action.status = "executed"
            except Exception as exc:  # noqa: BLE001 - never lose the action on failure
                logger.error("place_order failed for %s: %s", action.symbol, exc)
                action.status = "approved"
        else:
            logger.info("%s (%s)", _NO_BROKER_MSG, action.symbol)
            action.status = "approved"

        state.approved_actions.append(action)
        state.execution_history.append(action)

    # Pending queue drained into approved_actions; paper_watchlist is preserved.
    state.pending_actions = []
    return state


async def execution(state: PortfolioState) -> PortfolioState:
    """Stage PASS stocks, then finalize them once a human has approved.

    The graph gates this node with ``interrupt_before=["execution"]``, so by the
    time it runs the human has already approved (or the run ended at the pause).
    Staging is idempotent (deduped against existing pending_actions).
    """
    _stage_pending(state)
    if state.human_approved:
        _process_approved(state)
    return state
