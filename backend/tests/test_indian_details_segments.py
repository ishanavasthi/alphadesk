"""`segments` on `get_indian_stocks_details` (issue #60).

The Research agent's details call already passes
`segments=["analyst", "news"]` and the tool already forwards the parameter to
the MCP server — the "cheap win" from BACKLOG.md §segments is wired, so what
is pinned here is that it stays wired:

1. The tool forwards `segments` verbatim to `_call_mcp_tool` (and defaults to
   `None`, not to a fabricated segment).
2. `_research_one` asks for exactly `["analyst", "news"]` — analyst ratings
   and news sentiment, the two segments the backlog names.

No network: the MCP transport and the LLM are both stubbed.
"""

from __future__ import annotations

from typing import Any

import agents.research as research_mod
from agents.research import _research_one
from graph.state import ScanResult
from tools import ind_money
from tools.ind_money import StockDetailsResponse, get_indian_stocks_details


async def test_tool_forwards_segments_to_the_mcp_server(
    monkeypatch,
) -> None:
    seen: dict[str, Any] = {}

    async def _fake_call(tool: str, args: dict[str, Any]) -> Any:
        seen["tool"] = tool
        seen["args"] = args
        return {}

    monkeypatch.setattr(ind_money, "_call_mcp_tool", _fake_call)
    result = await get_indian_stocks_details.ainvoke(
        {"ind_keys": ["INDS00577"], "segments": ["analyst", "news"]}
    )
    assert seen["tool"] == "get_indian_stocks_details"
    assert seen["args"] == {"ind_keys": ["INDS00577"], "segments": ["analyst", "news"]}
    assert isinstance(result, StockDetailsResponse)


async def test_tool_defaults_to_no_segments(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    async def _fake_call(tool: str, args: dict[str, Any]) -> Any:
        seen["args"] = args
        return {}

    monkeypatch.setattr(ind_money, "_call_mcp_tool", _fake_call)
    await get_indian_stocks_details.ainvoke({"ind_keys": ["INDS00577"]})
    assert seen["args"] == {"ind_keys": ["INDS00577"], "segments": None}


async def test_research_asks_for_analyst_and_news(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class _FakeDetailsTool:
        @staticmethod
        async def ainvoke(args: dict[str, Any]) -> Any:
            seen["args"] = args
            return "Error: stubbed"  # not a response → no detail, no F&O branch

    class _FakeLlm:
        async def ainvoke(self, prompt: str) -> Any:
            return type("Msg", (), {"content": "stub summary"})()

    monkeypatch.setattr(research_mod, "get_indian_stocks_details", _FakeDetailsTool())
    monkeypatch.setattr(research_mod, "_get_llm", lambda: _FakeLlm())
    report = await _research_one(
        ScanResult(symbol="RELIANCE", ind_key="INDS00577", signal="top gainer")
    )
    assert seen["args"] == {
        "ind_keys": ["INDS00577"],
        "segments": ["analyst", "news"],
    }
    assert "stub summary" in report.summary
