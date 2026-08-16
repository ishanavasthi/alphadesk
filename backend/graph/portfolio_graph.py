"""The portfolio overview graph (card A1) — parallel specialists → synthesizer.

A LangGraph fan-out over the **verified metrics**: four read-and-reason
specialists run in parallel and a synthesizer writes the narrative. Unlike the
Lab research graph there is deliberately **no human-approval gate, no risk
guardrail, no ``interrupt_before`` and no checkpointer** — this graph only reads
and describes; it never proposes an action.

It carries no holdings itself: numbers are computed in Python before the graph is
invoked (`agents.portfolio.metrics`) and passed in as the metric catalog. The
graph reasons over labels and precomputed displays, so nothing sensitive travels
through it — and it is invoked with
:func:`graph.portfolio_config.portfolio_runnable_config`, which keeps LangSmith
tracing off even when ``LANGCHAIN_TRACING_V2=true`` (F1's kill switch; the
assertion F1 deferred lives in ``tests/test_portfolio_graph.py``).

If the LLM is unavailable the whole thing degrades: the graph raises
``OverviewLLMError`` out of a specialist and the caller renders the panel's
"AI overview unavailable" state with every computed number still intact.
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, Awaitable, Callable, Mapping, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.portfolio.agents import (
    SPECIALISTS,
    OverviewLLMError,
    default_llm_factory,
    run_specialist,
    run_synthesizer,
    scripted_overview_prose,
)
from agents.portfolio.metrics import Metric
from agents.portfolio.narrative import invented_figures, parse_prose
from graph.portfolio_config import portfolio_runnable_config

_log = logging.getLogger(__name__)

LLMFactory = Callable[[], Any]


def _merge_findings(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    out = dict(a or {})
    out.update(b or {})
    return out


class OverviewState(TypedDict, total=False):
    #: The computed metric catalog, keyed by stable metric key. Read-only input.
    metrics: dict[str, Metric]
    #: How each specialist's LLM is built. Injected so tests use a fake model.
    llm_factory: LLMFactory
    #: Specialist findings, merged as parallel nodes complete.
    findings: Annotated[dict[str, str], _merge_findings]
    #: Per-node status events, for the SSE stream / observability.
    agents: Annotated[list[dict[str, Any]], operator.add]
    #: The final narrative (list of paragraph dicts).
    narrative: list[dict[str, Any]]
    #: Whether the synthesizer fell back to the deterministic scripted prose.
    scripted: bool


def _specialist_node(name: str, focus: str, keys: tuple[str, ...]) -> Callable[[OverviewState], Awaitable[dict]]:
    async def node(state: OverviewState) -> dict:
        metrics = state.get("metrics", {})
        llm = state["llm_factory"]()
        text = await run_specialist(name, focus, keys, metrics, llm)
        return {
            "findings": {name: text},
            "agents": [{"node": name, "status": "done", "empty": not text.strip()}],
        }

    return node


async def _synthesizer_node(state: OverviewState) -> dict:
    metrics: Mapping[str, Metric] = state.get("metrics", {})
    findings = state.get("findings", {})
    llm = state["llm_factory"]()

    prose = await run_synthesizer(findings, metrics, llm)
    narrative = parse_prose(prose, metrics)

    scripted = False
    # Ironclad invariant: every figure in the narrative must trace to a computed
    # metric. If the model slipped a bare numeral past the token rule, fall back
    # to the deterministic scripted prose (which cites tokens only), so the panel
    # never shows a number that did not come from Python.
    metric_list = list(metrics.values())
    if not narrative or invented_figures(narrative, metric_list):
        if narrative and invented_figures(narrative, metric_list):
            _log.warning("overview synthesizer produced an untraceable figure; using scripted prose")
        narrative = parse_prose(scripted_overview_prose(metrics), metrics)
        scripted = True

    return {
        "narrative": narrative,
        "scripted": scripted,
        "agents": [{"node": "synthesizer", "status": "done"}],
    }


def build_portfolio_overview_graph() -> Any:
    """Compile the fan-out → synthesizer graph. No checkpointer, no interrupt."""
    builder: StateGraph = StateGraph(OverviewState)
    for name, focus, keys in SPECIALISTS:
        builder.add_node(name, _specialist_node(name, focus, keys))
        builder.add_edge(START, name)
        builder.add_edge(name, "synthesizer")
    builder.add_node("synthesizer", _synthesizer_node)
    builder.add_edge("synthesizer", END)
    return builder.compile()


#: Process-wide compiled graph. The model is chosen per-invocation via the
#: ``llm_factory`` in the input state, so one compiled graph serves every user.
alphaDesk_portfolio_graph = build_portfolio_overview_graph()


def _initial_state(
    metrics: Mapping[str, Metric],
    llm_factory: Optional[LLMFactory],
) -> OverviewState:
    return {
        "metrics": dict(metrics),
        "llm_factory": llm_factory or default_llm_factory,
        "findings": {},
        "agents": [],
    }


async def run_overview_graph(
    metrics: Mapping[str, Metric],
    *,
    llm_factory: Optional[LLMFactory] = None,
    thread_id: Optional[str] = None,
    graph: Any = None,
) -> OverviewState:
    """Invoke the graph once (non-streaming), with tracing off. For tests/demo.

    Raises ``OverviewLLMError`` if the model is unavailable — callers degrade.
    """
    graph = graph or alphaDesk_portfolio_graph
    config = portfolio_runnable_config(thread_id=thread_id, run_name="alphaDesk_overview")
    return await graph.ainvoke(_initial_state(metrics, llm_factory), config)


def overview_stream(
    metrics: Mapping[str, Metric],
    *,
    llm_factory: Optional[LLMFactory] = None,
    thread_id: Optional[str] = None,
    graph: Any = None,
):
    """Async iterator of per-node update chunks, with tracing off.

    Yields LangGraph ``updates`` chunks so the SSE route can emit one event per
    specialist as it completes. Raises ``OverviewLLMError`` on model failure.
    """
    graph = graph or alphaDesk_portfolio_graph
    config = portfolio_runnable_config(thread_id=thread_id, run_name="alphaDesk_overview")
    return graph.astream(_initial_state(metrics, llm_factory), config, stream_mode="updates")


__all__ = [
    "OverviewLLMError",
    "OverviewState",
    "alphaDesk_portfolio_graph",
    "build_portfolio_overview_graph",
    "overview_stream",
    "run_overview_graph",
]
