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


# Fabricated free-prose numbers the OLD substring detector let pass because each
# shares a substring with a real display (top weight 21.7%, top-3 64.6%, HHI
# 0.17, net worth ₹5,00,000-ish). The structural detector must catch every one.
_SUBSTRING_ADJACENT = [
    "The return was 42% last quarter.",  # fully out of range (old check caught this)
    "Concentration is 1.7% of the book.",  # substring of the 21.7% top-weight chip
    "There are 5 concentrated names.",  # substring of a display digit
    "About 07,655 rupees sit in cash.",  # a rupee-grouping fragment
    "The book returned 4.6% net.",  # substring of the 64.6% top-3 chip
]


@pytest.mark.parametrize("bad_prose", _SUBSTRING_ADJACENT)
async def test_fabricated_free_prose_number_falls_back_to_scripted(bad_prose: str) -> None:
    by_key = _metrics()
    # Every case writes a numeral as free prose (no [[token]]) — it must trip the
    # fallback, INCLUDING the ones that are substrings of a real display.
    state = await run_overview_graph(
        by_key, llm_factory=lambda: _FakeLLM(bad_prose), thread_id="u2"
    )
    assert state["scripted"] is True
    # The scripted fallback carries no free-prose figure of its own.
    assert invented_figures(state["narrative"]) == []


async def test_detector_is_structural_not_substring() -> None:
    """A digit in a text segment is invented even if it is a display substring."""
    by_key = _metrics()
    top = by_key["top_holding_weight"].display  # e.g. "23.5%"
    # A chip carries the real display (allowed); prose carries a substring digit.
    narrative = [
        {"segments": [
            {"metric": "top_holding_weight", "display": top, "label": "x", "detail": None, "available": True},
            {"text": f" — but only 3.5% is liquid."},
        ]}
    ]
    offenders = invented_figures(narrative)
    assert offenders  # the free-prose "3.5%" is flagged despite being a substring
    # The chip's own display is NOT flagged (it is a chip, not free prose).
    assert top not in offenders


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


async def test_overview_stream_also_carries_tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SSE streaming path (`overview_stream`) uses the same tracing-off config."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    captured: dict = {}

    class _SpyGraph:
        def astream(self, state, config, stream_mode=None):
            captured["config"] = config

            async def _gen():
                if False:  # pragma: no cover - an empty async generator
                    yield {}

            return _gen()

    from graph.portfolio_graph import overview_stream

    async for _ in overview_stream(
        _metrics(), llm_factory=lambda: _FakeLLM("x"), thread_id="u5", graph=_SpyGraph()
    ):
        pass
    assert is_tracing_disabled(captured["config"]) is True
    assert has_live_tracer(captured["config"]) is False


async def test_every_prompt_is_routed_through_redact() -> None:
    """redact() is actually applied on BOTH the specialist and synthesizer paths.

    A metric detail is poisoned with an email; it must not survive into any
    prompt sent to the model. Deleting the redact() call from either
    `_catalog` (specialist) or `run_synthesizer` (synthesizer) makes this fail.
    """
    import dataclasses

    by_key = dict(_metrics())
    poison = "reach-me@leak.example.com"
    by_key["equity_share"] = dataclasses.replace(by_key["equity_share"], detail=poison)

    prompts: list[str] = []

    class _RecordingLLM:
        async def ainvoke(self, messages):
            prompts.append(messages[-1][1])
            return _Msg("cites [[equity_share]].")

    await run_overview_graph(by_key, llm_factory=lambda: _RecordingLLM(), thread_id="u6")

    assert prompts, "no prompts were captured"
    # allocation_critic + sip_health cite equity_share, and the synthesizer lists
    # every available metric — so the poisoned detail reaches multiple prompts.
    assert any("[[equity_share]]" in p for p in prompts)
    for prompt in prompts:
        assert poison not in prompt, "an un-redacted PII value reached a prompt"
        assert "leak.example.com" not in prompt
