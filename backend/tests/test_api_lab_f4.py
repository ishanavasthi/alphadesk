"""The F4 Lab gates and per-user state, over HTTP against the real app + DB.

Card F4 threads a `user_id` through the Lab, keys its in-memory state by user,
closes the last ambient path (`POST /analyze`), and persists the paper watchlist.
The claims pinned here:

1. **`/analyze` is nobody's-by-default no more.** No identity -> 401; identity
   but no link -> 409 ("link your account"); a linked caller runs. With
   `ALPHADESK_SINGLE_TENANT` unset there is no ambient fallback — the endpoint
   never runs for a request it cannot name.
2. **A caller sees and acts on only their own.** User A reading or approving
   user B's run is a **404**, not a 403 — existence is not leaked. `/analyses`
   lists only the caller's.
3. **The watchlist persists.** It survives a simulated restart with its thesis
   intact and its opaque `run_id` degrading to "no longer available", and it
   cascade-deletes with the user.

The MCP and the graph are mocked (the brief: "mock the MCP for the gating
tests"); the database is the real throwaway Postgres from `docs/TESTING/F1.md`.
"""

from __future__ import annotations

from contextlib import suppress
from decimal import Decimal
from typing import Any, Iterator, Optional

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from api import main
from db.models import User, Watchlist
from services import adoption, snapshots
from tests.clerk_stub import bearer, clerk, clerk_key  # noqa: F401
from tools import ind_money_auth as auth

USER_A = "user_2aaaaaaaaaaaaaaaaaaaaaaaa"
USER_B = "user_2bbbbbbbbbbbbbbbbbbbbbbbb"


# --------------------------------------------------------------------------- #
# A graph stand-in — no MCP, no LLM
# --------------------------------------------------------------------------- #
class _Snapshot:
    def __init__(self, values: dict, nxt: tuple) -> None:
        self.values = values
        self.next = nxt


class FakeGraph:
    """Streams two nodes then finishes; `awaiting` decides whether it pauses.

    Enough shape for `analyze()` to walk its stream, read a final state and
    decide status — without a real MCP call or model behind it.
    """

    def __init__(self, *, awaiting: bool = False) -> None:
        self.awaiting = awaiting
        self.calls = 0
        self.last_state: Optional[Any] = None

    async def astream(self, initial, config, stream_mode="updates"):
        self.calls += 1
        self.last_state = initial
        yield {"scanner": {"scan_results": [{"symbol": "AAA"}]}}
        yield {"analyst": {"analyst_recommendations": [{"symbol": "AAA"}]}}

    async def aget_state(self, config):
        values = {"user_query": "q", "user_id": "local", "analyst_recommendations": []}
        return _Snapshot(values, ("execution",) if self.awaiting else ())


async def _no_fx() -> Optional[Decimal]:
    return None


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("IND_MONEY_MCP_URL", "https://mcp.example/does-not-exist")
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    monkeypatch.delenv("ALPHADESK_ADMIN_SECRET", raising=False)
    monkeypatch.delenv(adoption.OPERATOR_EMAIL_ENV, raising=False)
    auth.reset_auth_stores()
    adoption.reset_adoption_cache()
    # The Lab registries are module globals — a test must not inherit another's.
    main._RUNS.clear()
    main._ACTIONS.clear()
    main._ANALYSES.clear()
    main._PAPER_WATCHLIST.clear()
    yield
    auth.reset_auth_stores()
    adoption.reset_adoption_cache()
    main._RUNS.clear()
    main._ACTIONS.clear()
    main._ANALYSES.clear()
    main._PAPER_WATCHLIST.clear()
    main.app.dependency_overrides.clear()


@pytest.fixture
async def client(db_env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The app over ASGI with S1's opportunistic capture defanged (as in F3)."""
    monkeypatch.setattr(snapshots, "fetch_usd_inr", _no_fx)
    monkeypatch.setattr(snapshots, "CALL_SPACING_SECONDS", 0.0)
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://testserver"
    ) as http:
        yield http
    for task in list(snapshots._background):
        with suppress(Exception):
            await task


def _linked(*users: str):
    """Patch `auth_status` so exactly `users` read as linked to IND Money."""
    linked = set(users)

    async def fake(user_id: Optional[str] = None) -> dict:
        return {"authenticated": user_id in linked}

    return fake


async def _drain(response) -> str:
    body = b""
    async for chunk in response.aiter_bytes():
        body += chunk
    return body.decode()


# --------------------------------------------------------------------------- #
# 1. /analyze — the last ambient path, now gated
# --------------------------------------------------------------------------- #
async def test_analyze_without_identity_is_401(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No token, single-tenant off: there is no ambient identity to run as."""
    graph = FakeGraph()
    monkeypatch.setattr(main, "alphaDesk_graph", graph)
    monkeypatch.setattr(main, "auth_status", _linked("local", USER_A, USER_B))

    response = await client.post("/analyze", json={"query": "momentum IT"})
    assert response.status_code == 401
    # And it never ran — no ambient fallback reached the graph.
    assert graph.calls == 0


async def test_analyze_for_an_unlinked_user_is_409(
    client: Any, clerk: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = FakeGraph()
    monkeypatch.setattr(main, "alphaDesk_graph", graph)
    monkeypatch.setattr(main, "auth_status", _linked(USER_A))  # B is not linked

    response = await client.post(
        "/analyze", json={"query": "q"}, headers=bearer(clerk, USER_B)
    )
    assert response.status_code == 409
    assert "link" in response.json()["detail"].lower()
    assert graph.calls == 0


async def test_analyze_runs_for_a_linked_user(
    client: Any, clerk: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = FakeGraph(awaiting=False)
    monkeypatch.setattr(main, "alphaDesk_graph", graph)
    monkeypatch.setattr(main, "auth_status", _linked(USER_A))

    async with client.stream(
        "POST", "/analyze", json={"query": "q"}, headers=bearer(clerk, USER_A)
    ) as response:
        assert response.status_code == 200
        body = await _drain(response)

    assert graph.calls == 1
    assert "event: complete" in body
    # The run was stamped with the caller and bound as the run identity.
    assert graph.last_state.user_id == USER_A
    run_id = next(iter(main._RUNS))
    assert main._RUNS[run_id]["user_id"] == USER_A


async def test_analyze_binding_does_not_leak_after_the_run(
    client: Any, clerk: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run-user ContextVar is reset in `finally`, so a later userless call
    resolves to the ambient identity, not the last Lab caller."""
    graph = FakeGraph()
    monkeypatch.setattr(main, "alphaDesk_graph", graph)
    monkeypatch.setattr(main, "auth_status", _linked(USER_A))

    async with client.stream(
        "POST", "/analyze", json={"query": "q"}, headers=bearer(clerk, USER_A)
    ) as response:
        await _drain(response)

    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    assert await auth.ambient_user_id() == auth.LOCAL_USER_ID


# --------------------------------------------------------------------------- #
# 2. Ownership — a caller sees only their own (404, never 403)
# --------------------------------------------------------------------------- #
def _seed_run(run_id: str, user_id: str, *, action_id: Optional[str] = None) -> None:
    main._RUNS[run_id] = {
        "run_uuid": run_id,
        "user_id": user_id,
        "query": "q",
        "status": "awaiting_approval" if action_id else "completed",
        "action_id": action_id,
    }
    main._ANALYSES[run_id] = {
        "run_id": run_id,
        "user_id": user_id,
        "query": "q",
        "status": "completed",
        "analyst_recommendations": [],
        "risk_assessments": [],
        "created_at": "2026-08-16T00:00:00+00:00",
    }
    if action_id:
        main._ACTIONS[action_id] = run_id


async def test_one_user_cannot_read_anothers_analysis(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    _seed_run("run-A", USER_A)
    response = await client.get("/analysis/run-A", headers=bearer(clerk, USER_B))
    assert response.status_code == 404  # not 403 — existence is not leaked
    # The owner still reads it.
    owner = await client.get("/analysis/run-A", headers=bearer(clerk, USER_A))
    assert owner.status_code == 200


async def test_one_user_cannot_read_anothers_run_status(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    _seed_run("run-A", USER_A)
    response = await client.get("/status/run-A", headers=bearer(clerk, USER_B))
    assert response.status_code == 404


async def test_one_user_cannot_approve_anothers_run(
    client: Any, clerk: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approving is the one that would actually move money-shaped state, so the
    ownership check must fire *before* the graph resumes."""
    resumed = {"count": 0}

    async def spy(**kwargs):
        resumed["count"] += 1
        raise AssertionError("must not resume another user's run")

    monkeypatch.setattr(main, "resume_after_approval", spy)
    _seed_run("run-A", USER_A, action_id="act-A")

    response = await client.post(
        "/approve",
        json={"action_id": "act-A", "approved": True},
        headers=bearer(clerk, USER_B),
    )
    assert response.status_code == 404
    assert resumed["count"] == 0


async def test_analyses_lists_only_the_callers(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    _seed_run("run-A1", USER_A)
    _seed_run("run-A2", USER_A)
    _seed_run("run-B1", USER_B)

    a = (await client.get("/analyses", headers=bearer(clerk, USER_A))).json()
    b = (await client.get("/analyses", headers=bearer(clerk, USER_B))).json()

    assert {i["run_id"] for i in a["items"]} == {"run-A1", "run-A2"}
    assert {i["run_id"] for i in b["items"]} == {"run-B1"}


# --------------------------------------------------------------------------- #
# 3. The watchlist persists, degrades gracefully, and cascades
# --------------------------------------------------------------------------- #
async def _insert_user(db_env: Any, user_id: str) -> None:
    async with db_env() as session:
        await auth.ensure_user_row(session, user_id)


async def test_watchlist_survives_a_restart_with_thesis_and_a_dead_run_link(
    client: Any, clerk: rsa.RSAPrivateKey, db_env: Any
) -> None:
    """Persist a decision, wipe the in-memory registry (the "restart"), and read
    it back: the thesis is intact and the opaque run link no longer resolves."""
    await _insert_user(db_env, USER_A)
    rows = [
        {
            "user_id": USER_A,
            "symbol": "AAA",
            "company": "Alpha Ltd",
            "thesis": "cheap, catalysts near",
            "confidence": 0.82,
            "action": "buy",
            "risk_verdict": "PASS",
            "query": "momentum IT",
            "run_id": "run-gone",
        }
    ]
    async with db_env() as session:
        await main._persist_watchlist(session, USER_A, rows)

    # A "restart": in-memory runs are gone, the DB row is not.
    main._RUNS.clear()
    main._ANALYSES.clear()

    body = (await client.get("/watchlist", headers=bearer(clerk, USER_A))).json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["symbol"] == "AAA"
    assert item["thesis"] == "cheap, catalysts near"
    assert item["confidence"] == 0.82
    assert item["run_id"] == "run-gone"
    # The run link degraded gracefully — not an error, just "no longer available".
    assert item["run_available"] is False
    gone = await client.get("/analysis/run-gone", headers=bearer(clerk, USER_A))
    assert gone.status_code == 404


async def test_watchlist_is_per_user_and_first_decision_wins(
    client: Any, clerk: rsa.RSAPrivateKey, db_env: Any
) -> None:
    await _insert_user(db_env, USER_A)
    await _insert_user(db_env, USER_B)
    async with db_env() as session:
        await main._persist_watchlist(
            session, USER_A, [{"user_id": USER_A, "symbol": "AAA", "thesis": "first"}]
        )
        # Same (user, symbol) again — the first decision must stand.
        await main._persist_watchlist(
            session, USER_A, [{"user_id": USER_A, "symbol": "AAA", "thesis": "second"}]
        )
        await main._persist_watchlist(
            session, USER_B, [{"user_id": USER_B, "symbol": "BBB", "thesis": "b"}]
        )

    a = (await client.get("/watchlist", headers=bearer(clerk, USER_A))).json()
    b = (await client.get("/watchlist", headers=bearer(clerk, USER_B))).json()
    assert [i["symbol"] for i in a["items"]] == ["AAA"]
    assert a["items"][0]["thesis"] == "first"
    assert [i["symbol"] for i in b["items"]] == ["BBB"]


async def test_watchlist_delete_is_scoped_to_the_caller(
    client: Any, clerk: rsa.RSAPrivateKey, db_env: Any
) -> None:
    await _insert_user(db_env, USER_A)
    await _insert_user(db_env, USER_B)
    async with db_env() as session:
        await main._persist_watchlist(
            session, USER_A, [{"user_id": USER_A, "symbol": "AAA"}]
        )
        await main._persist_watchlist(
            session, USER_B, [{"user_id": USER_B, "symbol": "AAA"}]
        )

    # B deleting "AAA" must not touch A's identically-named row.
    await client.delete("/watchlist/AAA", headers=bearer(clerk, USER_B))
    a = (await client.get("/watchlist", headers=bearer(clerk, USER_A))).json()
    assert [i["symbol"] for i in a["items"]] == ["AAA"]


async def test_deleting_a_user_cascades_to_their_watchlist(
    client: Any, db_env: Any
) -> None:
    """L1's delete-my-data leans on this being a DB-level cascade (raw SQL)."""
    await _insert_user(db_env, USER_A)
    async with db_env() as session:
        await main._persist_watchlist(
            session, USER_A, [{"user_id": USER_A, "symbol": "AAA"}]
        )

    async with db_env() as session:
        before = (
            await session.execute(
                select(Watchlist).where(Watchlist.user_id == USER_A)
            )
        ).scalars().all()
        assert len(before) == 1
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": USER_A})
        await session.commit()
        after = (
            await session.execute(
                select(Watchlist).where(Watchlist.user_id == USER_A)
            )
        ).scalars().all()
    assert after == []
