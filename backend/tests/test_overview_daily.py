"""The AI overview is written at most once per IST day (issue #14).

The five agents behind `/portfolio/overview` are the only thing on the dashboard
that costs money per view, and before this the cost was per *page load*: a
refresh, a re-login, or a walk back from the Lab paid for the paragraph again.
Four properties make "once a day" safe, and each one is a test here:

1. **A saved day replays.** The second visit gets the same payload back over the
   same SSE contract, with no `update` events, **no model call** and no spend.
2. **Regenerate is the one thing that spends.** `?force=1` re-runs the agents and
   *overwrites* the day's saved copy, so the button is never a lie.
3. **A degraded run never locks the day.** No key, over budget, or a mid-stream
   model failure returns as today's answer but is not saved — the next visit
   retries instead of inheriting an empty narrative until tomorrow.
4. **No database is no saving**, and no behaviour change: with `DATABASE_URL`
   unset every visit streams live exactly as it did before.

Driven through the real ASGI app against the migrated test database, with the
connector and the model both replaced — no source call and no OpenAI spend.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import graph.portfolio_graph as pg
from agents.portfolio.agents import OverviewLLMError
from agents.portfolio.spend import get_limiter
from api.main import app
from api.routes.overview import _overview_key
from api.routes.portfolio import connector_for_request
from db.models import User
from portfolio.connectors import StubConnector
from services import portfolio_cache
from services import snapshots as svc
from services.snapshots import attributed_day

USER = "local"


class _CountingLLM:
    """The A1 fake model, plus a tally of how often it was actually asked."""

    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def ainvoke(self, messages):
        self.calls += 1
        if self.fail:
            raise OverviewLLMError("the model is down")
        user = messages[-1][1]
        if "Combine the specialist" in user:
            return _Msg(
                "Holds [[holdings_count]] names with [[equity_share]] equity.\n\n"
                "HHI [[herfindahl_index]]."
            )
        return _Msg("cites [[equity_share]].")


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-tenant dev with a (fake) key, so a headerless run reaches the graph."""
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    get_limiter().reset()


@pytest_asyncio.fixture
async def api(test_database_url: str, monkeypatch: pytest.MonkeyPatch):
    """Client, sessionmaker, connector and the one model every run shares.

    Same shape as `test_portfolio_cache.py`: the app's engine is a process-wide
    singleton bound to whatever loop built it, so the session dependency is
    overridden rather than pretended to be reusable.
    """
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[Any]:
        async with maker() as session:
            yield session

    monkeypatch.setattr(svc, "get_sessionmaker", lambda: maker)

    # The saved row is FK'd to `users`, so the caller has to exist. In production
    # `portfolio_identity` writes that row from the verified token.
    async with maker() as session:
        session.add(User(id=USER))
        await session.commit()

    llm = _CountingLLM()
    monkeypatch.setattr(pg, "default_llm_factory", lambda: llm)
    app.dependency_overrides[svc.optional_session] = _session
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, maker, llm
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(
                text("TRUNCATE users, portfolio_cache RESTART IDENTITY CASCADE")
            )
        await engine.dispose()


def _events(raw: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        event = "message"
        data_lines: list[str] = []
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


async def _saved(maker: Any) -> dict | None:
    key = _overview_key(attributed_day(datetime.now(timezone.utc)))
    async with maker() as session:
        return await portfolio_cache.get(session, USER, key)


# --------------------------------------------------------------------------- #
# Saved and replayed
# --------------------------------------------------------------------------- #
async def test_the_second_visit_of_the_day_replays_without_the_model(api: Any) -> None:
    client, maker, llm = api

    first = await client.post("/portfolio/overview")
    assert first.status_code == 200
    live = _complete(first.text)
    assert live["degraded"] is False
    assert live["narrative"]
    assert llm.calls > 0, "the first run of the day writes the narrative"
    spent = get_limiter().snapshot()["global"]

    calls_after_first = llm.calls
    second = await client.post("/portfolio/overview")
    assert second.status_code == 200
    replay = _complete(second.text)

    # Same narrative and same numbers — the chips still match the rail.
    assert replay["narrative"] == live["narrative"]
    assert replay["metrics"] == live["metrics"]
    assert replay["saved"] is True
    # Nothing ran: no model call, no new spend, and no per-agent progress.
    assert llm.calls == calls_after_first
    assert get_limiter().snapshot()["global"] == spent
    kinds = [e for e, _ in _events(second.text)]
    assert kinds[0] == "start", "the SSE contract is unchanged for a replay"
    assert "update" not in kinds


async def test_force_regenerates_and_overwrites_the_saved_day(api: Any) -> None:
    client, maker, llm = api

    await client.post("/portfolio/overview")
    calls_after_first = llm.calls
    before = await _saved(maker)
    assert before is not None

    forced = await client.post("/portfolio/overview?force=1")
    assert forced.status_code == 200
    assert llm.calls > calls_after_first, "Regenerate must reach the model"
    fresh = _complete(forced.text)
    assert "saved" not in fresh, "a forced run is live, not a replay"
    assert "update" in [e for e, _ in _events(forced.text)]

    # The day's saved copy is the run that just happened, not the earlier one.
    after = await _saved(maker)
    assert after is not None
    assert after["narrative"] == fresh["narrative"]


# --------------------------------------------------------------------------- #
# Degradation never claims the day
# --------------------------------------------------------------------------- #
async def test_a_missing_key_degrades_without_saving_and_the_next_visit_retries(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, maker, llm = api
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    degraded = _complete((await client.post("/portfolio/overview")).text)
    assert degraded["degraded"] is True
    assert degraded["reason"] == "llm_unavailable"
    assert await _saved(maker) is None, "a degraded run must not claim the day"

    # The key comes back and the very next visit writes the day for real.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    good = _complete((await client.post("/portfolio/overview")).text)
    assert good["degraded"] is False
    assert good["narrative"]
    assert await _saved(maker) is not None


async def test_a_mid_stream_model_failure_is_not_saved(api: Any) -> None:
    client, maker, llm = api
    llm.fail = True

    degraded = _complete((await client.post("/portfolio/overview")).text)
    assert degraded["degraded"] is True
    assert degraded["reason"] == "llm_unavailable"
    assert degraded["metrics"], "every computed number still renders"
    assert await _saved(maker) is None


# --------------------------------------------------------------------------- #
# DB-optional
# --------------------------------------------------------------------------- #
async def test_with_no_database_every_visit_streams_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DB-optional invariant: no `DATABASE_URL`, no saving, no change."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    llm = _CountingLLM()
    monkeypatch.setattr(pg, "default_llm_factory", lambda: llm)
    app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            first = _complete((await client.post("/portfolio/overview")).text)
            calls_after_first = llm.calls
            second = _complete((await client.post("/portfolio/overview")).text)
    finally:
        app.dependency_overrides.clear()

    assert first["degraded"] is False
    assert second["degraded"] is False
    assert "saved" not in second
    assert llm.calls > calls_after_first, "without a database both visits are live"
