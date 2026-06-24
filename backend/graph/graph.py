"""LangGraph assembly for AlphaDesk.

Wires the five agent nodes into a single StateGraph over ``PortfolioState``:

    scanner -> research -> analyst -> risk_manager --(conditional)--> execution -> END
                                                  \\--(all REJECT)--> END

Conditional routing after ``risk_manager``:
    - any assessment PASS or FLAG  -> execution
    - otherwise (all REJECT / none) -> END (rejection_reason already set upstream)

A human-in-the-loop pause is added with ``interrupt_before=["execution"]``: the
graph stops *before* the execution node so a human can inspect the risk
assessments and approve. Resume by setting ``human_approved=True`` on the thread
and re-invoking (see :func:`resume_after_approval`).

The compiled graph is exported as ``alphaDesk_graph``.
"""

from __future__ import annotations

from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents.analyst import analyst
from agents.execution import execution
from agents.research import research
from agents.risk_manager import risk_manager
from agents.scanner import scanner
from graph.state import PortfolioState


def route_after_risk(state: PortfolioState) -> str:
    """Route to execution if anything passed risk, otherwise end the run."""
    if any(a.decision in ("PASS", "FLAG") for a in state.risk_assessments):
        return "execution"
    return END


def _build_graph():
    builder = StateGraph(PortfolioState)

    builder.add_node("scanner", scanner)
    builder.add_node("research", research)
    builder.add_node("analyst", analyst)
    builder.add_node("risk_manager", risk_manager)
    builder.add_node("execution", execution)

    builder.add_edge(START, "scanner")
    builder.add_edge("scanner", "research")
    builder.add_edge("research", "analyst")
    builder.add_edge("analyst", "risk_manager")
    builder.add_conditional_edges(
        "risk_manager",
        route_after_risk,
        {"execution": "execution", END: END},
    )
    builder.add_edge("execution", END)

    # MemorySaver is required for interrupt_before to pause/resume on a thread.
    return builder.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["execution"],
    )


alphaDesk_graph = _build_graph()


def _as_state(result: object) -> PortfolioState:
    if isinstance(result, PortfolioState):
        return result
    return PortfolioState.model_validate(result)


async def run_graph(user_query: str, thread_id: str = "default") -> PortfolioState:
    """Run the research desk for ``user_query`` and return the resulting state.

    With the HiTL interrupt, this returns the state *paused before execution*
    (research + recommendations + risk assessments populated, awaiting human
    approval). Call :func:`resume_after_approval` to finalize.
    """
    config = {"configurable": {"thread_id": thread_id}}
    initial = PortfolioState(user_query=user_query)
    result = await alphaDesk_graph.ainvoke(initial, config)
    return _as_state(result)


async def resume_after_approval(
    thread_id: str = "default",
    approved: bool = True,
    rejection_reason: Optional[str] = None,
) -> PortfolioState:
    """Resume a paused run after a human decision; returns the final state.

    Sets ``human_approved`` (and optionally ``rejection_reason``) on the thread,
    then resumes execution. If ``approved`` is True the Execution agent stages PASS
    stocks and finalizes them into ``approved_actions`` / ``paper_watchlist``.
    """
    config = {"configurable": {"thread_id": thread_id}}
    update: dict = {"human_approved": approved}
    if rejection_reason is not None:
        update["rejection_reason"] = rejection_reason
    await alphaDesk_graph.aupdate_state(config, update)
    result = await alphaDesk_graph.ainvoke(None, config)
    return _as_state(result)
