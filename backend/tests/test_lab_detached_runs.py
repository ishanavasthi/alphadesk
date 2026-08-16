"""A Lab run outlives its SSE listener (issue #27).

`/analyze` used to execute the LangGraph pipeline *inside* the response
generator, so a browser navigating away aborted the request, cancelled the
generator and killed the run mid-flight — while `_RUNS[run_id]` went on claiming
`running` forever. The pipeline is now a background task and the response only
drains that task's queue. What is pinned here:

1. **The connected-client contract is unchanged** — same events, same order.
2. **Abandoning the response does not kill the run** — it still reaches a
   terminal status and still writes `_ANALYSES`.
3. **Deliberate cancellation still exists** — the account-deletion purge cancels
   the user's in-flight task instead of leaking a run for a deleted account.

The graph is a slow stub; no MCP, no LLM, no database (`_lab_identity` is
overridden, which is the only reason this suite needs neither Clerk nor
Postgres).
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Iterator, Optional

import pytest
from httpx import ASGITransport, AsyncClient

from api import main

USER = "user_2ddddddddddddddddddddddddd"


class _Snapshot:
    def __init__(self, values: dict, nxt: tuple) -> None:
        self.values = values
        self.next = nxt


class SlowGraph:
    """Streams two nodes with a real await between them, so a run is catchable.

    `gate` (when set) is awaited before the second node, which lets a test hold
    the pipeline mid-run while it abandons the response or deletes the account.
    """

    def __init__(self, *, gate: Optional[asyncio.Event] = None) -> None:
        self.gate = gate
        self.finished = False

    async def astream(self, initial, config, stream_mode="updates"):
        yield {"scanner": {"scan_results": [{"symbol": "AAA"}]}}
        if self.gate is not None:
            await self.gate.wait()
        else:
            await asyncio.sleep(0)
        yield {"analyst": {"analyst_recommendations": [{"symbol": "AAA"}]}}
        self.finished = True

    async def aget_state(self, config):
        return _Snapshot({"user_query": "q", "analyst_recommendations": []}, ())


@pytest.fixture(autouse=True)
def lab(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A caller who is signed in and linked, over an empty Lab registry."""

    async def identity() -> str:
        return USER

    async def linked(user_id: Optional[str] = None) -> dict:
        return {"authenticated": True}

    monkeypatch.setattr(main, "auth_status", linked)
    main.app.dependency_overrides[main._lab_identity] = identity
    main._RUNS.clear()
    main._ACTIONS.clear()
    main._ANALYSES.clear()
    yield
    for record in list(main._RUNS.values()):
        task = record.get("task")
        if task is not None and not task.done():
            task.cancel()
    main._RUNS.clear()
    main._ACTIONS.clear()
    main._ANALYSES.clear()
    main.app.dependency_overrides.clear()


@pytest.fixture
async def client() -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://testserver"
    ) as http:
        yield http


def _events(body: str) -> list:
    return [
        line[len("event: ") :]
        for line in body.splitlines()
        if line.startswith("event: ")
    ]


async def _settle(run_id: str) -> None:
    """Wait for the run's background task, however it ended."""
    task = main._RUNS[run_id]["task"]
    with suppress(asyncio.CancelledError, Exception):
        await task


async def test_a_connected_client_sees_the_same_event_sequence(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start, one update per node, then complete — byte-identical to before."""
    monkeypatch.setattr(main, "alphaDesk_graph", SlowGraph())

    async with client.stream("POST", "/analyze", json={"query": "q"}) as response:
        assert response.status_code == 200
        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk

    assert _events(body.decode()) == ["start", "update", "update", "complete"]
    run_id = next(iter(main._RUNS))
    assert main._RUNS[run_id]["status"] == "completed"
    assert main._ANALYSES[run_id]["status"] == "completed"


async def _start_and_abandon() -> str:
    """Start a run, read one frame, then drop the response mid-stream.

    Driving the endpoint's `StreamingResponse` directly rather than over the test
    client is deliberate: httpx's `ASGITransport` awaits the whole ASGI app
    before it hands back a response, so it can never model a client that walks
    away mid-run. Closing the body iterator is exactly what Starlette does when
    the socket goes — the case this issue is about.
    """
    response = await main.analyze(main.AnalyzeRequest(query="q"), user_id=USER)
    frames = response.body_iterator
    assert (await frames.__anext__()).startswith("event: start")
    await frames.aclose()
    return next(iter(main._RUNS))


async def test_abandoning_the_stream_does_not_kill_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The acceptance case: drop the stream mid-run, the run still finishes."""
    gate = asyncio.Event()
    graph = SlowGraph(gate=gate)
    monkeypatch.setattr(main, "alphaDesk_graph", graph)

    run_id = await _start_and_abandon()
    assert main._RUNS[run_id]["status"] == "running"

    gate.set()
    await _settle(run_id)

    assert graph.finished is True
    assert main._RUNS[run_id]["status"] == "completed"
    assert main._ANALYSES[run_id]["run_id"] == run_id


async def test_account_deletion_cancels_an_in_flight_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DELETE /account`'s purge must not leave a deleted user's run spending."""
    gate = asyncio.Event()
    graph = SlowGraph(gate=gate)
    monkeypatch.setattr(main, "alphaDesk_graph", graph)

    run_id = await _start_and_abandon()
    task = main._RUNS[run_id]["task"]

    main.purge_user_lab_state(USER)  # exactly what DELETE /account calls

    with suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert graph.finished is False
    # The record went with the purge; nothing resurrected it on the way out.
    assert run_id not in main._RUNS
