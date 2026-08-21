"""Live OpenRouter calls — proves the env swap reaches a real endpoint.

Gated: runs only when ``RUN_OPENROUTER_LIVE=1`` and an ``OPENROUTER_API_KEY`` is
present, so ordinary CI spends nothing. Two calls, one per family — an overview
specialist and a Lab agent — because the whole point of the vars is that each
family can be pointed somewhere new independently. Keep it to two calls.

The model comes from ``OPENROUTER_LIVE_MODEL`` (default ``stealth/ox-alpha``) so
this test does not rot when a stealth slug is retired.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()  # pick up backend/.env so a local OPENROUTER_API_KEY reaches this test

from agents.llm import OPENROUTER_BASE_URL, get_lab_llm, get_overview_llm
from agents.portfolio.agents import run_specialist
from agents.portfolio.metrics import compute_metrics, metrics_by_key
from tests.test_portfolio_metrics import _holding, _snapshot

_MODEL = (os.environ.get("OPENROUTER_LIVE_MODEL") or "").strip() or "stealth/ox-alpha"
_RUN = os.environ.get("RUN_OPENROUTER_LIVE") == "1" and bool(
    os.environ.get("OPENROUTER_API_KEY")
)

pytestmark = pytest.mark.skipif(
    not _RUN, reason="set RUN_OPENROUTER_LIVE=1 with OPENROUTER_API_KEY to run"
)


@pytest.fixture
def _on_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point both families at OpenRouter exactly as a deploy would."""
    monkeypatch.setenv("OVERVIEW_PROVIDER", "openrouter")
    monkeypatch.setenv("OVERVIEW_MODEL", _MODEL)
    monkeypatch.setenv("LAB_PROVIDER", "openrouter")
    monkeypatch.setenv("LAB_MODEL", _MODEL)


async def test_overview_specialist_on_openrouter(_on_openrouter: None) -> None:
    snap = _snapshot(
        net_worth=Decimal("500000"),
        gross_value=Decimal("500000"),
        invested_total=Decimal("450000"),
    )
    holdings = [
        _holding("A", "300000", invested="280000", name="Anvil", atype="IND_STOCK"),
        _holding("B", "200000", invested="170000", name="Alpha Fund", atype="MF"),
    ]
    by_key = metrics_by_key(compute_metrics(snap, holdings))

    llm = get_overview_llm("gpt-4o-mini", timeout=60)
    assert isinstance(llm, ChatOpenAI)
    assert str(llm.root_client.base_url).rstrip("/") == OPENROUTER_BASE_URL
    assert llm.model_name == _MODEL

    text = await run_specialist(
        "concentration_risk",
        "how concentrated the book is",
        ("herfindahl_index", "top_holding_weight", "top_holding_name"),
        by_key,
        llm,
    )
    assert text.strip()
    # The no-invented-numbers contract must hold on this provider too: the
    # specialist cites tokens, it does not type figures.
    assert "[[" in text


async def test_lab_agent_on_openrouter(_on_openrouter: None) -> None:
    llm = get_lab_llm("analyst", "openai/gpt-oss-120b")
    assert isinstance(llm, ChatOpenAI)
    assert str(llm.root_client.base_url).rstrip("/") == OPENROUTER_BASE_URL
    assert llm.model_name == _MODEL

    message = await llm.ainvoke(
        [("human", "Reply with exactly one word: OK")]
    )
    content = message.content
    if isinstance(content, list):
        content = "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    assert "OK" in str(content).upper()


async def test_structured_output_survives_the_swap(_on_openrouter: None) -> None:
    """The trap this card actually hit: strict json_schema is not universal.

    ``stealth/ox-alpha`` advertises ``tools`` but not ``structured_outputs``.
    With langchain's default method the Analyst's parse fails, ``_analyze_one``
    swallows it, and every candidate is silently dropped — a run that looks like
    "no opportunities" rather than a misconfiguration.
    """
    from agents.analyst import _AnalystOutput
    from agents.llm import structured

    llm = structured(get_lab_llm("analyst", "openai/gpt-oss-120b"), _AnalystOutput)
    out = await llm.ainvoke(
        "Analyze RELIANCE: PE 24.1, RSI 61, refining margins improved QoQ. "
        "Give a full recommendation."
    )
    assert out.action in {"buy", "hold", "avoid"}
    assert 0.0 <= out.confidence <= 1.0
    assert out.bull_thesis.strip() and out.bear_thesis.strip()
