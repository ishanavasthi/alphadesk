"""FastAPI entrypoint for AlphaDesk.

Serves the LangGraph research desk over HTTP. Run with::

    cd backend && uvicorn api.main:app --reload --port 8000

Endpoints:
    POST /analyze          -> kick off a run; streams agent updates via SSE,
                              ends with analyst recommendations + risk assessments.
    POST /approve          -> resume a run paused at the human-in-the-loop gate.
    GET  /status/{run_id}  -> current state of a run.

Tracking: each run gets a UUID that is passed to LangGraph as the ``run_id`` in
the config, so it becomes the LangSmith trace root id — the same id is used as
the checkpointer thread id and the app-level run handle. LangSmith tracing stays
on via env (LANGCHAIN_TRACING_V2); it is never disabled here.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

# Load backend/.env so LLM keys, LANGCHAIN_*, IND_MONEY_MCP_URL are present
# before the graph and agents read them.
load_dotenv()

from api.routes.internal import router as internal_router  # noqa: E402
from api.routes.portfolio import router as portfolio_router  # noqa: E402
from graph.graph import alphaDesk_graph, resume_after_approval  # noqa: E402
from graph.state import PortfolioState  # noqa: E402
from api.deps import (  # noqa: E402
    bearer_token,
    register_identity,
    verify_token,
)
from services.snapshots import optional_session  # noqa: E402
from tools.ind_money_auth import (  # noqa: E402
    LOCAL_USER_ID,
    MCPAuthError,
    OAuthStateError,
    auth_status,
    begin_login,
    complete_login,
    logout,
    single_tenant_mode,
)

# Where IND Money redirects after login. Must be reachable in the browser and
# match the registered redirect_uri. 127.0.0.1 avoids IPv6 (::1) issues.
AUTH_REDIRECT_URI = os.environ.get(
    "IND_MONEY_AUTH_REDIRECT", "http://127.0.0.1:8000/auth/callback"
)

app = FastAPI(title="AlphaDesk", version="0.1.0")

# CORS origins. Local dev (localhost / 127.0.0.1 any port) is always allowed.
# In production set CORS_ALLOW_ORIGINS to the deployed frontend origin(s),
# comma-separated, e.g. "https://alphadesk.ishanavasthi.in,https://alphadesk.vercel.app".
# Optionally set CORS_ALLOW_ORIGIN_REGEX (e.g. to allow Vercel preview deploys:
#   https://[a-z0-9-]+\.vercel\.app ).
_PROD_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",")
    if o.strip()
]
_LOCAL_REGEX = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
_EXTRA_REGEX = os.environ.get("CORS_ALLOW_ORIGIN_REGEX", "").strip()
_ORIGIN_REGEX = f"{_LOCAL_REGEX}|{_EXTRA_REGEX}" if _EXTRA_REGEX else _LOCAL_REGEX

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", *_PROD_ORIGINS],
    allow_origin_regex=_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Read-only portfolio routes for the D1 dashboard (card D1). Every route on this
# router is gated by the same admin secret as /auth/login — see
# `api/routes/portfolio.py`, which reuses `_require_admin` below.
app.include_router(portfolio_router)

# Machine-to-machine routes for the nightly snapshot job (card S1). Guarded by
# CRON_SECRET, **not** by the admin gate above — a scheduled runner is not an
# operator and must not hold a secret that can read holdings or unlink the
# account. See `api/routes/internal.py`.
app.include_router(internal_router)


# --------------------------------------------------------------------------- #
# In-memory run registry (swap for a store/DB in production)
# --------------------------------------------------------------------------- #
# run_id -> {"run_uuid": UUID, "query": str, "status": str, "action_id": str|None, ...}
_RUNS: Dict[str, Dict[str, Any]] = {}
# action_id -> run_id (the pending approval batch a /approve call targets)
_ACTIONS: Dict[str, str] = {}
# symbol -> {symbol, run_id, query, added_at}; the cumulative paper watchlist
# across runs (in-memory; swap for a store in production).
_PAPER_WATCHLIST: Dict[str, Dict[str, Any]] = {}
# run_id -> full analysis payload, so a run survives a browser refresh and can be
# reopened at /a/<run_id> (in-memory; swap for a store to survive backend restart).
_ANALYSES: Dict[str, Dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_watchlist(run_id: str, symbols: list) -> None:
    query = _RUNS.get(run_id, {}).get("query")
    for sym in symbols or []:
        if sym not in _PAPER_WATCHLIST:
            _PAPER_WATCHLIST[sym] = {
                "symbol": sym,
                "run_id": run_id,
                "query": query,
                "added_at": _now_iso(),
            }

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_PROGRESS_FIELDS = (
    "scan_results",
    "research_reports",
    "analyst_recommendations",
    "risk_assessments",
    "pending_actions",
    "approved_actions",
    "paper_watchlist",
)


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    query: str = Field(..., description="Natural-language research request.")


class ApproveRequest(BaseModel):
    action_id: str = Field(..., description="Pending approval id returned by /analyze.")
    approved: bool = Field(..., description="True to execute, False to reject.")


# --------------------------------------------------------------------------- #
# Config + serialization helpers
# --------------------------------------------------------------------------- #
def _trace_config(run_id: str, run_uuid: uuid.UUID) -> Dict[str, Any]:
    """Config that ties the LangGraph/LangSmith root run id to our run_id."""
    return {
        "configurable": {"thread_id": run_id},
        "run_id": run_uuid,
        "run_name": "alphaDesk",
        "tags": ["alphaDesk", "api"],
        "metadata": {"app_run_id": run_id},
    }


def _thread_config(run_id: str) -> Dict[str, Any]:
    """Thread-only config for resume / state reads (no new trace root)."""
    return {"configurable": {"thread_id": run_id}}


def _as_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return {}


def _state_dict(snapshot: Any) -> Dict[str, Any]:
    """JSON-serializable view of a graph state snapshot."""
    values = getattr(snapshot, "values", None) or {}
    try:
        return PortfolioState.model_validate(values).model_dump()
    except Exception:  # noqa: BLE001 - best-effort fallback
        return {k: (v.model_dump() if isinstance(v, BaseModel) else v) for k, v in values.items()}


def _summarize_update(node: str, payload: Any) -> Dict[str, Any]:
    """Compact per-node progress event (counts only — never raw payloads)."""
    data = _as_dict(payload)
    summary: Dict[str, Any] = {"node": node}
    for key in _PROGRESS_FIELDS:
        value = data.get(key)
        if isinstance(value, (list, dict)):
            summary[f"{key}_count"] = len(value)
    if data.get("rejection_reason"):
        summary["rejection_reason"] = data["rejection_reason"]
    return summary


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/")
async def root() -> Dict[str, str]:
    return {"service": "AlphaDesk", "version": "0.1.0"}


def _auth_html(message: str, ok: bool = False) -> HTMLResponse:
    color = "#16c784" if ok else "#e5484d"
    mark = "✓" if ok else "✕"
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><title>IND Money</title></head>
<body style="background:#0a0b0d;color:#e6e9ef;font-family:ui-sans-serif,system-ui;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
  <div style="text-align:center">
    <div style="color:{color};font-size:20px;margin-bottom:8px">{mark} {message}</div>
    <div style="color:#8b919e;font-size:13px">You can close this window.</div>
  </div>
</body></html>"""
    )


def _require_admin(
    x_alphadesk_admin_secret: Optional[str] = Header(default=None),
) -> None:
    """Interim C0 gate on connect/disconnect until per-user auth lands (V2 F3).

    The IND Money link is still a process-wide singleton, so whoever can reach
    /auth/login links their account to the whole server and whoever can reach
    /auth/logout severs it for everyone. Until F3 makes links per-user, both are
    operator-only actions guarded by the ``ALPHADESK_ADMIN_SECRET`` shared
    secret (sent as the ``x-alphadesk-admin-secret`` header). Fail-closed: with
    the secret unset, the endpoints are locked rather than open. Single-tenant
    dev mode (``ALPHADESK_SINGLE_TENANT=1``, local only) bypasses the gate so
    the in-app Connect button keeps working on the operator's machine.
    """
    if single_tenant_mode():
        return
    expected = os.environ.get("ALPHADESK_ADMIN_SECRET") or ""
    supplied = x_alphadesk_admin_secret or ""
    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail=(
                "Connecting or disconnecting IND Money is an operator-only "
                "action on this deployment."
            ),
        )


async def _link_identity(
    authorization: Optional[str] = Header(default=None),
    session: Optional[Any] = Depends(optional_session),
) -> str:
    """Whose broker link is being created or destroyed. **JWT only.**

    `/auth/login` and `/auth/logout` are the two endpoints the interim C0 admin
    header is deliberately *not* accepted on. Linking is identity-bound as of
    F3: a link written under a shared operator secret would have no owner, which
    is the precise shape of the process-wide credential this card deleted. A
    caller with no verified identity has no link to make.

    The one exception is single-tenant dev (`ALPHADESK_SINGLE_TENANT=1`, the
    operator's own machine), which has no Clerk instance to mint a token from
    and links as ``"local"`` exactly as it did before this card.
    """
    if not authorization and single_tenant_mode():
        return LOCAL_USER_ID
    claims = await asyncio.to_thread(verify_token, bearer_token(authorization))
    if session is None:
        return str(claims["sub"])
    return await register_identity(session, claims)


async def _status_identity(
    authorization: Optional[str] = Header(default=None),
    x_alphadesk_admin_secret: Optional[str] = Header(default=None),
    session: Optional[Any] = Depends(optional_session),
) -> Optional[str]:
    """Whose link status to report, or None for "nobody in particular".

    Reading is softer than writing, so this one does fall back to the interim
    admin identity — the v1 research page polls it with no session while
    `NEXT_PUBLIC_AUTH_ENABLED` is off. What it will not do is answer for a user
    it cannot name: an anonymous caller now gets a flat "not connected" instead
    of a truthful readout of *someone else's* link, which is what this endpoint
    used to hand to the whole internet.

    It registers the identity like every other authenticated entry point.
    That matters more here than it looks: a browser that has just signed in
    calls `/auth/status` **first**, so if this were the one path that skipped
    registration, operator adoption would never fire for the person it exists
    for — which is exactly what the first live run of this card found.
    """
    if authorization:
        claims = await asyncio.to_thread(verify_token, bearer_token(authorization))
        if session is None:
            return str(claims["sub"])
        return await register_identity(session, claims)
    if single_tenant_mode():
        return LOCAL_USER_ID
    expected = os.environ.get("ALPHADESK_ADMIN_SECRET") or ""
    supplied = x_alphadesk_admin_secret or ""
    if expected and supplied and secrets.compare_digest(supplied, expected):
        from services.adoption import admin_identity

        return await admin_identity()
    return None


@app.get("/auth/status")
async def auth_status_endpoint(
    user_id: Optional[str] = Depends(_status_identity),
) -> Dict[str, object]:
    """Whether **this caller** is linked to the IND Money MCP."""
    if user_id is None:
        return {
            "authenticated": False,
            "source": None,
            "expires_at": None,
            "expires_in_sec": None,
            "revoked": False,
            "user_id": None,
        }
    return await auth_status(user_id)


@app.post("/auth/login")
async def auth_login_endpoint(
    user_id: str = Depends(_link_identity),
) -> Dict[str, str]:
    """Begin an OAuth login for the signed-in user; returns the URL to open.

    The `state` this mints is written to `oauth_pending` bound to ``user_id``
    before the URL is handed out, so the callback can establish the owner
    without trusting anything the returning browser carries.
    """
    try:
        url = await begin_login(user_id, AUTH_REDIRECT_URI)
    except MCPAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"authorization_url": url}


@app.post("/auth/logout")
async def auth_logout_endpoint(
    user_id: str = Depends(_link_identity),
) -> Dict[str, object]:
    """Unlink IND Money for the signed-in user: revoke upstream, then delete."""
    return await logout(user_id)


@app.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback_endpoint(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> HTMLResponse:
    """OAuth redirect target — exchanges the code for tokens.

    **No identity is read off this request.** Not a cookie, not a header, not a
    query parameter beyond the OAuth ones: the owner comes from the
    `oauth_pending` row `state` names, which was written before the user ever
    left for the broker. A state that is unknown, already used, or older than
    ten minutes links nothing and says so.
    """
    if error:
        return _auth_html(f"Authorization failed: {error}")
    if not code or not state:
        return _auth_html("Missing authorization code or state.")
    try:
        await complete_login(code, state)
    except OAuthStateError as exc:
        return _auth_html(f"{exc} Nothing was connected.")
    except Exception:  # noqa: BLE001 - the message can carry broker payload text
        return _auth_html("Login failed. Please start the connection again.")
    return _auth_html("IND Money connected.", ok=True)


@app.post("/analyze")
async def analyze(body: AnalyzeRequest) -> StreamingResponse:
    """Run the research graph, streaming agent updates as Server-Sent Events.

    The stream ends with a ``complete`` event carrying the analyst
    recommendations and risk assessments. If anything passed risk, the run pauses
    at the human-in-the-loop gate and the event includes an ``action_id`` to pass
    to /approve.

    Refuses with 409 when IND Money is not connected: every agent downstream of
    the Scanner is fed by the MCP, so an unauthenticated run can only produce an
    empty "0 candidates" pipeline that looks like a real (but useless) result.
    """
    status_now = await auth_status()
    if not status_now.get("authenticated"):
        raise HTTPException(
            status_code=409,
            detail=(
                "IND Money is not connected. Connect IND Money first - the "
                "scanner has no market data without it."
            ),
        )

    run_uuid = uuid.uuid4()
    run_id = str(run_uuid)
    _RUNS[run_id] = {
        "run_uuid": run_uuid,
        "query": body.query,
        "status": "running",
        "action_id": None,
    }

    async def event_stream():
        config = _trace_config(run_id, run_uuid)
        yield _sse("start", {"run_id": run_id, "status": "running"})
        try:
            initial = PortfolioState(user_query=body.query)
            async for chunk in alphaDesk_graph.astream(initial, config, stream_mode="updates"):
                for node, payload in chunk.items():
                    if node.startswith("__"):  # skip interrupt/control markers
                        continue
                    yield _sse("update", _summarize_update(node, payload))

            snapshot = await alphaDesk_graph.aget_state(config)
            state = _state_dict(snapshot)
            awaiting = bool(getattr(snapshot, "next", None))

            action_id: Optional[str] = None
            if awaiting:
                status = "awaiting_approval"
                action_id = str(uuid.uuid4())
                _ACTIONS[action_id] = run_id
                _RUNS[run_id]["action_id"] = action_id
            elif state.get("rejection_reason"):
                status = "rejected"
            else:
                status = "completed"
            _RUNS[run_id]["status"] = status

            _ANALYSES[run_id] = {
                "run_id": run_id,
                "query": body.query,
                "status": status,
                "awaiting_approval": awaiting,
                "action_id": action_id,
                "analyst_recommendations": state.get("analyst_recommendations", []),
                "risk_assessments": state.get("risk_assessments", []),
                "rejection_reason": state.get("rejection_reason"),
                "paper_watchlist": state.get("paper_watchlist", []),
                "created_at": _now_iso(),
            }

            yield _sse(
                "complete",
                {
                    "run_id": run_id,
                    "status": status,
                    "awaiting_approval": awaiting,
                    "action_id": action_id,
                    "analyst_recommendations": state.get("analyst_recommendations", []),
                    "risk_assessments": state.get("risk_assessments", []),
                    "rejection_reason": state.get("rejection_reason"),
                },
            )
        except Exception as exc:  # noqa: BLE001 - surface error to the client
            _RUNS[run_id]["status"] = "error"
            _RUNS[run_id]["error"] = str(exc)
            yield _sse("error", {"run_id": run_id, "error": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/approve")
async def approve(body: ApproveRequest) -> Dict[str, Any]:
    """Resume a paused run after the human decision.

    approved=True  -> Execution stages PASS stocks into the paper watchlist and
                      finalizes them into approved_actions (placing real orders
                      only if a BrokerAdapter is configured).
    approved=False -> the staged batch is abandoned; nothing is added to the
                      paper watchlist. rejection_reason is recorded.
    """
    run_id = _ACTIONS.get(body.action_id) or (body.action_id if body.action_id in _RUNS else None)
    if run_id is None:
        raise HTTPException(status_code=404, detail="Unknown action_id")

    if body.approved:
        final = await resume_after_approval(thread_id=run_id, approved=True)
        _RUNS[run_id]["status"] = "completed"
        _record_watchlist(run_id, final.paper_watchlist)
        a = _ANALYSES.get(run_id)
        if a:
            a.update(
                status="completed",
                awaiting_approval=False,
                paper_watchlist=final.paper_watchlist,
            )
        return {"run_id": run_id, "status": "completed", "state": final.model_dump()}

    # Rejected: record reason, do not resume execution (no paper-watchlist writes).
    config = _thread_config(run_id)
    await alphaDesk_graph.aupdate_state(
        config, {"human_approved": False, "rejection_reason": "Rejected by human."}
    )
    _RUNS[run_id]["status"] = "rejected"
    a = _ANALYSES.get(run_id)
    if a:
        a.update(
            status="rejected",
            awaiting_approval=False,
            rejection_reason="Rejected by analyst.",
        )
    snapshot = await alphaDesk_graph.aget_state(config)
    return {"run_id": run_id, "status": "rejected", "state": _state_dict(snapshot)}


@app.get("/analyses")
async def list_analyses() -> Dict[str, Any]:
    """List stored analyses (most recent first)."""
    items = sorted(
        (
            {
                "run_id": a["run_id"],
                "query": a.get("query"),
                "status": a.get("status"),
                "created_at": a.get("created_at"),
                "count": len(a.get("analyst_recommendations", [])),
            }
            for a in _ANALYSES.values()
        ),
        key=lambda x: x.get("created_at") or "",
        reverse=True,
    )
    return {"count": len(items), "items": items}


@app.get("/analysis/{run_id}")
async def get_analysis(run_id: str) -> Dict[str, Any]:
    """Return the full stored analysis for a run, for the /a/<run_id> view."""
    analysis = _ANALYSES.get(run_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Unknown analysis")
    return analysis


@app.get("/watchlist")
async def get_watchlist() -> Dict[str, Any]:
    """Return the cumulative paper watchlist (stocks approved across runs)."""
    items = sorted(
        _PAPER_WATCHLIST.values(), key=lambda x: x.get("added_at", ""), reverse=True
    )
    return {"count": len(items), "items": items}


@app.delete("/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str) -> Dict[str, Any]:
    """Remove a symbol from the paper watchlist."""
    removed = _PAPER_WATCHLIST.pop(symbol, None) is not None
    return {"count": len(_PAPER_WATCHLIST), "symbol": symbol, "removed": removed}


@app.get("/status/{run_id}")
async def status(run_id: str) -> Dict[str, Any]:
    """Return the current state and status of a graph run."""
    record = _RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")

    snapshot = await alphaDesk_graph.aget_state(_thread_config(run_id))
    next_nodes = list(getattr(snapshot, "next", ()) or ())
    return {
        "run_id": run_id,
        "status": record["status"],
        "query": record.get("query"),
        "action_id": record.get("action_id"),
        "awaiting_approval": bool(next_nodes),
        "next": next_nodes,
        "state": _state_dict(snapshot),
    }
