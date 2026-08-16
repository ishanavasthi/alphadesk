"""One live OpenAI call (card A1) — proves real connectivity + provider routing.

Gated: it runs only when ``RUN_OPENAI_LIVE=1`` and an ``OPENAI_API_KEY`` is
present, so ordinary CI spends nothing. It makes **one** real call — a single
specialist against real OpenAI — to prove the happy path end to end; the full
multi-agent graph is proved with mocked LLMs elsewhere. Keep it to one call.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()  # pick up backend/.env so a local OPENAI_API_KEY reaches this test

from agents.portfolio.agents import default_llm_factory, run_specialist
from agents.portfolio.metrics import compute_metrics, metrics_by_key
from tests.test_portfolio_metrics import _snapshot, _holding

_RUN = os.environ.get("RUN_OPENAI_LIVE") == "1" and bool(os.environ.get("OPENAI_API_KEY"))

pytestmark = pytest.mark.skipif(not _RUN, reason="set RUN_OPENAI_LIVE=1 with OPENAI_API_KEY to run")


async def test_one_real_specialist_call() -> None:
    from decimal import Decimal

    snap = _snapshot(net_worth=Decimal("500000"), gross_value=Decimal("500000"), invested_total=Decimal("450000"))
    holdings = [
        _holding("A", "300000", invested="280000", name="Anvil", atype="IND_STOCK"),
        _holding("B", "200000", invested="170000", name="Alpha Fund", atype="MF"),
    ]
    by_key = metrics_by_key(compute_metrics(snap, holdings))

    llm = default_llm_factory()
    assert isinstance(llm, ChatOpenAI)
    assert str(llm.root_client.base_url).startswith("https://api.openai.com")

    name, focus, keys = "concentration_risk", "how concentrated the book is", (
        "herfindahl_index",
        "top_holding_weight",
        "top_holding_name",
    )
    text = await run_specialist(name, focus, keys, by_key, llm)
    assert text.strip()
    # The model was told to cite by token; it should have used at least one.
    assert "[[" in text
