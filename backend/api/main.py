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
import html
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

from sqlalchemy import delete as sa_delete  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from api.routes.internal import router as internal_router  # noqa: E402
from api.routes.overview import router as overview_router  # noqa: E402
from api.routes.portfolio import router as portfolio_router  # noqa: E402
from db.models import Watchlist, utcnow  # noqa: E402
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
    bind_run_user,
    complete_login,
    ensure_user_row,
    logout,
    single_tenant_mode,
    unbind_run_user,
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

# The AI overview panel (card A1): POST /portfolio/overview streams the narrative
# the multi-agent graph writes over Python-computed metrics. Same identity and
# source-error contract as the rest of /portfolio/*; degrades to metrics-only
# when the model is unavailable.
app.include_router(overview_router)

# Machine-to-machine routes for the nightly snapshot job (card S1). Guarded by
# CRON_SECRET, **not** by the admin gate above — a scheduled runner is not an
# operator and must not hold a secret that can read holdings or unlink the
# account. See `api/routes/internal.py`.
app.include_router(internal_router)


# --------------------------------------------------------------------------- #
# In-memory Lab state — per user, ephemeral by decision (card F4)
# --------------------------------------------------------------------------- #
# A Lab run is a labelled *simulation*, so it gets no persistence layer: the
# registry below lives in memory and is lost on a backend restart (a paused
# approval lost that way is an accepted trade — the UI says so). What it does get
# is **per-user keying** — every record carries the `user_id` it belongs to, and
# every read is scoped to the caller, so one user can never see or act on
# another's run. The **one** durable exception is the paper watchlist, which
# persists to the `watchlist` table (see `_persist_watchlist` / `read_watchlist`).
#
# run_id -> {"run_uuid": UUID, "user_id": str, "query": str, "status": str, ...}
_RUNS: Dict[str, Dict[str, Any]] = {}
# action_id -> run_id (the pending approval batch a /approve call targets).
_ACTIONS: Dict[str, str] = {}
# run_id -> full analysis payload (carries `user_id`), so a run survives a
# browser refresh and can be reopened at /lab/a/<run_id> until the process bounces.
_ANALYSES: Dict[str, Dict[str, Any]] = {}
# Fallback paper watchlist for a deployment with no DB: user_id -> symbol -> record.
# When `DATABASE_URL` is set the `watchlist` table is the source of truth and this
# is untouched. Single-tenant local dev with no Postgres keeps working through it.
_PAPER_WATCHLIST: Dict[str, Dict[str, Dict[str, Any]]] = {}

#: Columns of a persisted watchlist row, in the order the API returns them.
_WATCHLIST_FIELDS = (
    "symbol",
    "company",
    "thesis",
    "confidence",
    "action",
    "risk_verdict",
    "query",
    "run_id",
    "added_at",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owned_run(run_id: str, user_id: str, registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """A run/analysis record the caller owns, or 404 — **never 403**.

    A caller who is not the owner is told the run does not exist, not that it
    exists and is forbidden: a 403 leaks that the id is real (V2_PLAN §7).
    """
    record = registry.get(run_id)
    if record is None or record.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Unknown run")
    return record


def _decision_records(final: PortfolioState, run_id: str, user_id: str) -> list:
    """Denormalized watchlist rows for the symbols a run staged.

    Each row freezes the decision as it stood at approval — company, thesis,
    confidence, action, risk verdict — so it stays readable after the (in-memory)
    run is gone. `run_id` rides along as an opaque, non-FK reference.
    """
    recs = {r.symbol: r for r in final.analyst_recommendations}
    risks = {a.symbol: a for a in final.risk_assessments}
    names = {s.symbol: s.name for s in final.scan_results if s.name}
    query = _RUNS.get(run_id, {}).get("query")
    rows = []
    for sym in final.paper_watchlist or []:
        rec = recs.get(sym)
        risk = risks.get(sym)
        rows.append(
            {
                "user_id": user_id,
                "symbol": sym,
                "company": names.get(sym),
                "thesis": (rec.thesis or rec.bull_thesis) if rec else None,
                "confidence": rec.confidence if rec else None,
                "action": rec.action if rec else None,
                "risk_verdict": risk.decision if risk else None,
                "query": query,
                "run_id": run_id,
            }
        )
    return rows


async def _persist_watchlist(
    session: Optional[AsyncSession], user_id: str, rows: list
) -> None:
    """Add ``rows`` to ``user_id``'s watchlist. First decision per symbol wins.

    With a DB, upserts into the `watchlist` table (`ON CONFLICT DO NOTHING` on the
    `(user_id, symbol)` PK, so a stock already held keeps its original decision).
    With no DB, writes the same records into the in-memory per-user fallback.
    """
    if not rows:
        return
    if session is None:
        book = _PAPER_WATCHLIST.setdefault(user_id, {})
        for row in rows:
            book.setdefault(
                row["symbol"], {**row, "added_at": _now_iso()}
            )
        return

    # The FK onto `users` must resolve — a JWT caller was inserted by
    # `register_identity`, but a single-tenant `"local"` caller may not have a
    # row yet.
    await ensure_user_row(session, user_id)
    for row in rows:
        # `added_at` is filled here, not by the model default: a Core insert
        # against the table never sees `default_factory`, and the column is NOT
        # NULL — omitting it is an IntegrityError, not a silent wrong time.
        values = {"added_at": utcnow(), **row}
        await session.execute(
            pg_insert(Watchlist.__table__)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["user_id", "symbol"])
        )
    await session.commit()


async def read_watchlist(
    session: Optional[AsyncSession], user_id: str
) -> list:
    """``user_id``'s watchlist, newest first, as JSON-ready dicts."""
    if session is None:
        items = list(_PAPER_WATCHLIST.get(user_id, {}).values())
    else:
        result = await session.execute(
            select(Watchlist).where(Watchlist.user_id == user_id)
        )
        items = []
        for row in result.scalars().all():
            item = {f: getattr(row, f) for f in _WATCHLIST_FIELDS}
            item["added_at"] = row.added_at.isoformat() if row.added_at else None
            items.append(item)
    for item in items:
        rid = item.get("run_id")
        analysis = _ANALYSES.get(rid) if rid else None
        # "View original run" resolves only while the run is still in memory and
        # owned by this caller; otherwise the frontend shows "no longer available".
        item["run_available"] = bool(analysis and analysis.get("user_id") == user_id)
    items.sort(key=lambda x: x.get("added_at") or "", reverse=True)
    return items


async def _remove_watchlist(
    session: Optional[AsyncSession], user_id: str, symbol: str
) -> bool:
    """Drop one symbol from ``user_id``'s watchlist; True if a row was removed."""
    if session is None:
        removed = _PAPER_WATCHLIST.get(user_id, {}).pop(symbol, None) is not None
        return removed
    result = await session.execute(
        sa_delete(Watchlist).where(
            Watchlist.user_id == user_id, Watchlist.symbol == symbol
        )
    )
    await session.commit()
    return bool(result.rowcount or 0)

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
    """The one page `/auth/callback` ever renders.

    ``message`` is **always** HTML-escaped here rather than at the call sites.
    One of those call sites echoed an attacker-controlled query parameter
    (`?error=<script>…`) straight into the document — a reflected XSS on the
    backend origin, which is the origin that serves this OAuth callback. Escaping
    per-caller is a rule that has to be remembered every time somebody adds a
    branch; escaping here is a rule that cannot be forgotten.
    """
    message = html.escape(message)
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


def admin_secret_accepted(x_alphadesk_admin_secret: Optional[str]) -> bool:
    """**INTERIM (C0). The single place an admin header is ever accepted.**

    Every other site that honours `x-alphadesk-admin-secret` calls this. That is
    the point: this card's review found the acceptance logic had quietly grown a
    *third* copy — an inline `compare_digest` in `_status_identity` that no
    removal note mentioned — and a removal note that misses a site is how an
    interim gate outlives the release that was supposed to delete it.

    Fail-closed: an unset `ALPHADESK_ADMIN_SECRET` accepts nothing, so unsetting
    it on the Space is by itself enough to close every one of those sites.

    **The full removal checklist lives in `docs/SPECS/F3.md` §5 and must list
    every caller of this function.** At card L1: delete this, its three callers,
    and `frontend/lib/api.ts`'s `ADMIN_SECRET`.
    """
    if single_tenant_mode():
        return True
    expected = os.environ.get("ALPHADESK_ADMIN_SECRET") or ""
    supplied = x_alphadesk_admin_secret or ""
    if not expected or not supplied:
        return False
    return secrets.compare_digest(
        supplied.encode("latin-1", "replace"), expected.encode("utf-8")
    )


def _require_admin(
    x_alphadesk_admin_secret: Optional[str] = Header(default=None),
) -> None:
    """INTERIM (C0) — raise 401 unless the admin header is accepted.

    Kept as the raising wrapper because FastAPI dependencies want one. Single-
    tenant dev mode (``ALPHADESK_SINGLE_TENANT=1``, local only) passes, so the
    in-app Connect button keeps working on the operator's machine.
    """
    if not admin_secret_accepted(x_alphadesk_admin_secret):
        raise HTTPException(
            status_code=401,
            detail="This is an operator-only action on this deployment.",
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


async def _lab_identity(
    authorization: Optional[str] = Header(default=None),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> str:
    """Whose Lab run/state this is. **JWT only** — no ambient path (card F4).

    Every Lab endpoint (`/analyze`, `/approve`, `/analyses`, `/analysis/{id}`,
    `/watchlist`, `/status/{id}`) runs under a real per-user identity. This is
    the ambient path F3 left open being closed: `POST /analyze` used to run on
    `ambient_user_id()` — the operator, ungated — so an anonymous request burned
    Groq and read the operator's IND Money grant. Now a caller with no verified
    identity has no Lab, and gets a 401.

    The one exception is single-tenant dev (`ALPHADESK_SINGLE_TENANT=1`, the
    operator's own machine), which has no Clerk instance to mint a token from and
    runs as ``"local"`` — the same identity its broker link and pre-F3 data are
    keyed under. There is **no** interim admin-secret path here (unlike
    `/portfolio/*`): an admin-header Lab run would be exactly the unowned,
    ambient run this card removes.
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

    **This is the third interim admin-header site, and it is deliberate.** The
    brief made `/auth/login` and `/auth/logout` JWT-only because those *write* a
    link, and a link made under a shared secret has no owner. `/auth/status` is
    a read, and the v1 research page polls it with no session while
    `NEXT_PUBLIC_AUTH_ENABLED` is off — so it accepts the admin header, reports
    the operator's own link, and is listed in the L1 removal checklist
    (`docs/SPECS/F3.md` §5) alongside the other two. Acceptance goes through
    :func:`admin_secret_accepted` like everything else; there is no second copy
    of the comparison here any more.

    What it will not do is answer for a user it cannot name: an anonymous caller
    gets a flat "not connected" instead of a truthful readout of *someone
    else's* link, which is what this endpoint used to hand to the whole
    internet.

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
    if admin_secret_accepted(x_alphadesk_admin_secret):
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
            "undecryptable": False,
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
async def analyze(
    body: AnalyzeRequest,
    user_id: str = Depends(_lab_identity),
) -> StreamingResponse:
    """Run the research graph **as the caller**, streaming updates as SSE.

    The stream ends with a ``complete`` event carrying the analyst
    recommendations and risk assessments. If anything passed risk, the run pauses
    at the human-in-the-loop gate and the event includes an ``action_id`` to pass
    to /approve.

    Two gates, both per user (card F4 — this is the last ambient path F3 left
    open, now closed):

    - **Identity is required.** `_lab_identity` 401s a request with no verified
      Clerk token (single-tenant dev links as ``"local"``). There is no ambient
      fallback and no admin-secret path: a run is always somebody's.
    - **That somebody must be linked.** `auth_status(user_id)` is checked, not the
      process's ambient link. An unlinked caller gets a **409** telling them to
      link their account — every agent downstream of the Scanner is fed by the
      MCP, so an unlinked run can only produce an empty "0 candidates" pipeline
      that looks like a real (but useless) result, *and* running one would spend
      whichever grant the ambient path resolved to.

    The verified `user_id` is stamped onto `PortfolioState` and bound for the life
    of the run (`bind_run_user`), so the pipeline's IND Money MCP calls mint from
    *this* user's `AuthStore` — never a process-wide or "whoever linked first"
    grant.
    """
    status_now = await auth_status(user_id)
    if not status_now.get("authenticated"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Link your IND Money account to run the Lab. The scanner reads "
                "NSE market data through your IND Money connection and has none "
                "without it."
            ),
        )

    run_uuid = uuid.uuid4()
    run_id = str(run_uuid)
    _RUNS[run_id] = {
        "run_uuid": run_uuid,
        "user_id": user_id,
        "query": body.query,
        "status": "running",
        "action_id": None,
    }

    async def event_stream():
        config = _trace_config(run_id, run_uuid)
        # Bind the caller's identity for the run so every userless MCP tool call
        # the graph makes mints from this user's AuthStore. A ContextVar, so
        # concurrent runs never cross; reset in `finally` so it never leaks.
        token = bind_run_user(user_id)
        yield _sse("start", {"run_id": run_id, "status": "running"})
        try:
            initial = PortfolioState(user_query=body.query, user_id=user_id)
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
                "user_id": user_id,
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
        finally:
            unbind_run_user(token)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/approve")
async def approve(
    body: ApproveRequest,
    user_id: str = Depends(_lab_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> Dict[str, Any]:
    """Resume a paused run after the human decision — **only the caller's own**.

    approved=True  -> Execution stages PASS stocks into the paper watchlist and
                      finalizes them into approved_actions (placing real orders
                      only if a BrokerAdapter is configured). The approved stocks
                      are persisted to the caller's `watchlist` table as
                      denormalized decision records.
    approved=False -> the staged batch is abandoned; nothing is added to the
                      paper watchlist. rejection_reason is recorded.

    Resolving the action to a run the caller does not own answers **404**, never
    403: an id that maps to someone else's run is, to this caller, simply unknown.
    """
    run_id = _ACTIONS.get(body.action_id) or (body.action_id if body.action_id in _RUNS else None)
    if run_id is None:
        raise HTTPException(status_code=404, detail="Unknown action_id")
    _owned_run(run_id, user_id, _RUNS)

    if body.approved:
        # The graph's Execution node mints from the caller's AuthStore for the
        # resume, exactly as the run did — bind the same identity.
        token = bind_run_user(user_id)
        try:
            final = await resume_after_approval(thread_id=run_id, approved=True)
        finally:
            unbind_run_user(token)
        _RUNS[run_id]["status"] = "completed"
        await _persist_watchlist(
            session, user_id, _decision_records(final, run_id, user_id)
        )
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
async def list_analyses(
    user_id: str = Depends(_lab_identity),
) -> Dict[str, Any]:
    """List **the caller's** stored analyses (most recent first)."""
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
            if a.get("user_id") == user_id
        ),
        key=lambda x: x.get("created_at") or "",
        reverse=True,
    )
    return {"count": len(items), "items": items}


@app.get("/analysis/{run_id}")
async def get_analysis(
    run_id: str,
    user_id: str = Depends(_lab_identity),
) -> Dict[str, Any]:
    """The caller's full stored analysis for a run, for the /lab/a/<run_id> view.

    404 both when the run never existed and when it belongs to someone else — a
    caller cannot tell a stranger's run from a missing one. A watchlist row's
    opaque `run_id` that no longer resolves (the process bounced) also 404s here,
    which is the "this run is no longer available" the frontend renders.
    """
    return _owned_run(run_id, user_id, _ANALYSES)


@app.get("/watchlist")
async def get_watchlist(
    user_id: str = Depends(_lab_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> Dict[str, Any]:
    """The caller's cumulative paper watchlist (persisted; survives a restart)."""
    items = await read_watchlist(session, user_id)
    return {"count": len(items), "items": items}


@app.delete("/watchlist/{symbol}")
async def remove_from_watchlist(
    symbol: str,
    user_id: str = Depends(_lab_identity),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> Dict[str, Any]:
    """Remove a symbol from **the caller's** paper watchlist."""
    removed = await _remove_watchlist(session, user_id, symbol)
    items = await read_watchlist(session, user_id)
    return {"count": len(items), "symbol": symbol, "removed": removed}


@app.get("/status/{run_id}")
async def status(
    run_id: str,
    user_id: str = Depends(_lab_identity),
) -> Dict[str, Any]:
    """Return the current state and status of **the caller's** graph run."""
    record = _owned_run(run_id, user_id, _RUNS)

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
