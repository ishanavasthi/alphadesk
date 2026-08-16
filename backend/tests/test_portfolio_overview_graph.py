"""The overview graph (card A1) — figures, tracing-off, degradation.

Mocked LLM throughout: the multi-agent path is proved here with no OpenAI spend.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from agents.portfolio.agents import OverviewLLMError
from agents.portfolio.metrics import compute_metrics, metrics_by_key
from agents.portfolio.narrative import invented_figures
from graph.portfolio_config import has_live_tracer, is_tracing_disabled
from graph.portfolio_graph import run_overview_graph
from portfolio.models import AllocationSlice, AssetType, Holding, PortfolioSnapshot

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Returns token-only prose for specialists and the synthesizer."""

    def __init__(self, synth: str, spec: str = "cites [[equity_share]].") -> None:
        self._synth = synth
        self._spec = spec

    async def ainvoke(self, messages):
        user = messages[-1][1]
        if "Combine the specialist" in user:
            return _Msg(self._synth)
        return _Msg(self._spec)


class _DeadLLM:
    async def ainvoke(self, messages):
        raise RuntimeError("provider down")


def _metrics():
    slices = [
        AllocationSlice(label="IND_STOCK", asset_type=AssetType.IND_STOCK, asset_type_raw="IND_STOCK", current_value=Decimal("300000")),
        AllocationSlice(label="MF", asset_type=AssetType.MF, asset_type_raw="MF", current_value=Decimal("200000")),
    ]
    snap = PortfolioSnapshot(
        source="stub", as_of=NOW, net_worth=Decimal("500000"),
        gross_value=Decimal("500000"), invested_total=Decimal("450000"), by_asset_type=slices,
    )
    holdings = [
        Holding(source="stub", external_id="A", asset_type=AssetType.IND_STOCK, name="Anvil", invested_amount=Decimal("280000"), current_value=Decimal("300000"), pnl=Decimal("20000"), pnl_pct=Decimal("7.14"), as_of=NOW),
        Holding(source="stub", external_id="B", asset_type=AssetType.MF, name="Alpha Fund", invested_amount=Decimal("170000"), current_value=Decimal("200000"), pnl=Decimal("30000"), pnl_pct=Decimal("17.65"), as_of=NOW),
    ]
    return metrics_by_key(compute_metrics(snap, holdings))


async def test_every_narrative_figure_is_a_computed_metric() -> None:
    by_key = _metrics()
    synth = "Book holds [[holdings_count]] names, [[equity_share]] equity.\n\nHHI [[herfindahl_index]], top [[top_holding_weight]]."
    state = await run_overview_graph(by_key, llm_factory=lambda: _FakeLLM(synth), thread_id="u1")
    assert state["scripted"] is False
    assert invented_figures(state["narrative"], list(by_key.values())) == []
    # All four specialists plus the synthesizer ran.
    nodes = {a["node"] for a in state["agents"]}
    assert {"allocation_critic", "concentration_risk", "sip_health", "performance_attribution", "synthesizer"} <= nodes


async def test_untraceable_figure_falls_back_to_scripted() -> None:
    by_key = _metrics()
    # The model slips a bare numeral past the token rule.
    state = await run_overview_graph(
        by_key, llm_factory=lambda: _FakeLLM("The return was 42% last quarter."), thread_id="u2"
    )
    assert state["scripted"] is True
    # The scripted fallback still cites only computed figures.
    assert invented_figures(state["narrative"], list(by_key.values())) == []


async def test_llm_unavailable_raises_overview_error() -> None:
    by_key = _metrics()
    with pytest.raises(OverviewLLMError):
        await run_overview_graph(by_key, llm_factory=lambda: _DeadLLM(), thread_id="u3")


async def test_graph_is_invoked_with_tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with LANGCHAIN_TRACING_V2=true, the config carries no live tracer."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    captured: dict = {}

    class _SpyGraph:
        async def ainvoke(self, state, config):
            captured["config"] = config
            return {"narrative": [], "scripted": True, "agents": []}

    await run_overview_graph(_metrics(), llm_factory=lambda: _FakeLLM("x"), thread_id="u4", graph=_SpyGraph())
    assert is_tracing_disabled(captured["config"]) is True
    assert has_live_tracer(captured["config"]) is False
