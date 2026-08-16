"""`POST /portfolio/overview` (card A1) — the SSE contract and degradation.

The load-bearing acceptance: **with the LLM key removed the dashboard still
renders every computed number** and the panel degrades to "AI overview
unavailable" — never an error page. Proved here with the key deleted and with a
mocked LLM (no OpenAI spend). Also pins the demo artifact against the fixtures.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

import graph.portfolio_graph as pg
from agents.portfolio.metrics import compute_metrics, metrics_by_key
from agents.portfolio.spend import get_limiter
from api.main import app
from api.routes.portfolio import connector_for_request
from portfolio.connectors.stub import DEMO_FIXTURES, StubConnector
from portfolio.models import AssetType

@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Single-tenant off by default so `test_overview_requires_identity` sees the
    # 401. The authenticated tests opt in with `local_dev`.
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_limiter().reset()


@pytest.fixture
def local_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-tenant dev, so a headerless overview request is served as local.

    The interim admin path these tests used to authenticate through was removed
    at card L1 (F3 §5); single-tenant dev is the headerless replacement.
    """
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(connector_for_request, None)


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    async def ainvoke(self, messages):
        user = messages[-1][1]
        if "Combine the specialist" in user:
            return _Msg("Holds [[holdings_count]] names with [[equity_share]] equity.\n\nHHI [[herfindahl_index]].")
        return _Msg("cites [[equity_share]].")


def _events(raw: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        event = "message"
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            out.append((event, json.loads("\n".join(data_lines))))
    return out


def _complete(raw: str) -> dict:
    for event, data in _events(raw):
        if event == "complete":
            return data
    raise AssertionError("no complete event in stream")


# --------------------------------------------------------------------------- #
def test_overview_requires_identity(client: TestClient) -> None:
    assert client.post("/portfolio/overview").status_code == 401


def test_overview_degrades_when_llm_key_is_removed(
    client: TestClient, local_dev: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE hard requirement: no key ⇒ every computed number still renders."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resp = client.post("/portfolio/overview")
    assert resp.status_code == 200
    complete = _complete(resp.text)

    assert complete["degraded"] is True
    assert complete["reason"] == "llm_unavailable"
    assert complete["narrative"] == []

    # Every computed number is present and intact — this is the whole point.
    by_key = {m["key"]: m for m in complete["metrics"]}
    assert by_key["net_worth"]["display"] == "₹10,07,655"
    assert by_key["holdings_count"]["display"] == "9"
    assert by_key["pnl"]["display"] == "+₹88,905"
    assert by_key["rows_without_cost_basis"]["display"] == "2"
    # No LLM was constructed, so no spend slot was taken.
    assert get_limiter().snapshot()["global"] == 0


def test_overview_happy_path_with_mocked_llm(
    client: TestClient, local_dev: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(pg, "default_llm_factory", lambda: _FakeLLM())

    resp = client.post("/portfolio/overview")
    assert resp.status_code == 200
    events = _events(resp.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "start"
    assert "update" in kinds  # per-agent progress
    complete = _complete(resp.text)
    assert complete["degraded"] is False
    assert complete["narrative"]  # a real narrative
    assert complete["metrics"]

    # Every figure in the narrative traces to a returned metric display.
    displays = " ".join(m["display"] for m in complete["metrics"] if m["display"] != "—")
    import re

    def _fig(text: str):
        return re.findall(r"[₹%+\-−]?\d[\d,]*\.?\d*%?", text)

    for para in complete["narrative"]:
        for seg in para["segments"]:
            if "text" in seg:
                assert _fig(seg["text"]) == [], f"narrative prose carried a raw figure: {seg['text']!r}"
            elif "display" in seg:
                assert seg["display"] in displays


def test_overview_over_spend_cap_degrades(
    client: TestClient, local_dev: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("OVERVIEW_DAILY_USER_MAX", "0")
    monkeypatch.setattr(pg, "default_llm_factory", lambda: _FakeLLM())
    complete = _complete(client.post("/portfolio/overview").text)
    assert complete["degraded"] is True
    assert complete["reason"] == "spend_cap"


# --------------------------------------------------------------------------- #
# Demo artifact
# --------------------------------------------------------------------------- #
def test_demo_artifact_exists_and_matches_stub_fixtures() -> None:
    path = DEMO_FIXTURES / "overview.json"
    assert path.is_file(), "demo overview artifact is missing; run python -m agents.portfolio.demo"
    committed = json.loads(path.read_text(encoding="utf-8"))

    async def _recompute():
        c = StubConnector()
        snap = await c.fetch_snapshot("local")
        holdings = []
        seen = set()
        for s in snap.by_asset_type:
            at = s.asset_type
            if at is None:
                continue
            key = at.value if at is not AssetType.UNKNOWN else "UNKNOWN"
            if key in seen:
                continue
            seen.add(key)
            holdings.extend(await c.fetch_holdings("local", at))
        sips = await c.fetch_sips("local")
        return compute_metrics(snap, holdings, history=[], sips=sips)

    fresh = metrics_by_key(asyncio.run(_recompute()))
    committed_by_key = {m["key"]: m for m in committed["metrics"]}
    assert set(committed_by_key) == set(fresh)
    for key, m in fresh.items():
        assert committed_by_key[key]["display"] == m.display, key
    assert committed["narrative"], "committed narrative should not be empty"
    assert committed["degraded"] is False
