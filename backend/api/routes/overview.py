"""`POST /portfolio/overview` — the AI overview, streamed (card A1).

The contract in one paragraph: **the numbers are computed in Python and returned
no matter what; only the narrative needs the model.** The route fetches the
verified M1 snapshot/holdings/SIPs, computes the metric catalog
(`agents.portfolio.metrics`), and streams the narrative the multi-agent graph
writes over those metrics. If the model is unavailable — no key, provider down,
rate-limited, or over the app's daily spend ceiling — the stream still completes,
carrying every computed metric and a ``degraded`` flag, and the panel shows
"AI overview unavailable". It is never an error page.

Identity and rate-limit posture match `/portfolio/*` exactly: same
``portfolio_identity`` (a verified Clerk JWT, or the interim admin secret until
L1), same per-user connector, same typed-source-failure → HTTP mapping. A source
failure (unlinked, throttled, unreachable) is a normal JSON error the dashboard
already branches on — returned **before** the stream opens — because the panel
lives on a page that has already decided the source is reachable.

The graph is invoked with tracing off (`portfolio_runnable_config`), so holdings
reasoning never reaches LangSmith.

**The narrative is written at most once per IST day** (issue #14). The first
overview of the day runs the agents and saves its completed payload in the
`portfolio_cache` table under ``overview:<attributed IST day>``; every later
visit that day — a refresh, a re-login, a walk back from the Lab — replays that
saved payload and spends nothing. Only the Regenerate button (``?force=1``)
re-runs the agents, and it overwrites the day's saved copy. A degraded outcome is
returned but never saved, so a bad minute cannot lock the day.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agents.portfolio.agents import OverviewLLMError
from agents.portfolio.metrics import (
    HistoryPoint,
    compute_metrics,
    metrics_by_key,
    metrics_json,
    to_history_points,
)
from agents.portfolio.spend import get_limiter
from api.routes.portfolio import _fail, connector_for_request, portfolio_identity
from graph.portfolio_graph import overview_stream
from portfolio.connectors import PortfolioConnector
from portfolio.errors import PortfolioSourceError
from portfolio.models import AssetType, PortfolioSnapshot
from services import portfolio_cache
from services.snapshots import attributed_day, history_points, optional_session

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio", "overview"])

#: Polite spacing between per-asset-type holdings calls (the source rate-limits
#: 15/min per tool). Best-effort: a bucket that fails is skipped, its
#: concentration contribution simply absent rather than fatal.
_HOLDINGS_SPACING_S = 0.15

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

#: `?force=1` — the Regenerate button, and the only thing that spends. Everything
#: else that opens the dashboard today replays the day's saved narrative.
FORCE_QUERY = Query(False, description="Re-run the agents and overwrite today's saved overview.")


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _overview_key(day) -> str:
    """The saved-overview key for one attributed IST day.

    The day comes from `services.snapshots.attributed_day`, the one helper that
    owns calendar-day attribution here — a key built from UTC "today" would roll
    the narrative over at 05:30 IST, mid-evening for nobody and mid-morning for
    the reader.
    """
    return f"overview:{day.isoformat()}"


def _llm_configured() -> bool:
    """Whether an OpenAI key is present. No key ⇒ degrade without spending."""
    return bool((os.environ.get("OPENAI_API_KEY") or "").strip())


async def _gather_holdings(
    connector: PortfolioConnector, user_id: str, snapshot: PortfolioSnapshot
) -> list:
    """Holding rows for the buckets the snapshot actually reported.

    Every non-empty bucket the snapshot names, deduplicated — including the
    out-of-enum ``UNKNOWN`` bucket (the US wallet), queried **once**. IND Money
    refuses ``UNKNOWN`` with ``UnsupportedAssetType``; that is caught below and
    the bucket simply skipped, while the stub enumerates it — the same
    best-effort posture the dashboard's holdings loader takes, so the two agree
    on the holding count. A bucket that throttles or errors is likewise skipped.
    """
    holdings: list = []
    wanted: list[AssetType] = []
    seen: set[str] = set()
    for s in snapshot.by_asset_type:
        at = s.asset_type
        if at is None:
            continue
        if s.current_value is None or s.current_value <= 0:
            continue
        if at.value in seen:
            continue
        seen.add(at.value)
        wanted.append(at)

    for i, asset_type in enumerate(wanted):
        if i:
            await asyncio.sleep(_HOLDINGS_SPACING_S)
        try:
            rows = await connector.fetch_holdings(user_id, asset_type)
        except PortfolioSourceError:
            _log.info("overview: skipping bucket %s (source error)", asset_type.value)
            continue
        holdings.extend(rows)
    return holdings


async def _gather_sips(connector: PortfolioConnector, user_id: str) -> list:
    try:
        return await connector.fetch_sips(user_id)
    except PortfolioSourceError:
        return []
    except Exception:  # noqa: BLE001 - SIP shape is unverified; never fatal
        _log.info("overview: SIP fetch failed", exc_info=True)
        return []


async def _history(session: Optional[AsyncSession], user_id: str) -> list[HistoryPoint]:
    if session is None:
        return []
    try:
        rows = await history_points(session, user_id, days=45)
    except Exception:  # noqa: BLE001 - history is additive; never fatal
        _log.info("overview: history unavailable", exc_info=True)
        return []
    return to_history_points(rows)


@router.post("/overview")
async def overview(
    force: bool = FORCE_QUERY,
    user_id: str = Depends(portfolio_identity),
    connector: PortfolioConnector = Depends(connector_for_request),
    session: Optional[AsyncSession] = Depends(optional_session),
) -> StreamingResponse:
    """Compute the metrics, then stream the narrative the graph writes over them.

    Source failures are raised **now** (before the stream opens) as the same
    typed HTTP errors `/portfolio/*` returns. Once metrics exist, the response is
    a stream that always completes — degraded when the model cannot run.

    Unless ``force`` is set, a narrative already written today is replayed
    instead: the whole payload comes back as it was saved, so the metric chips in
    the prose still match the rail beside them. Without a database nothing is
    ever saved and every visit streams live, exactly as before issue #14.
    """
    day = attributed_day(datetime.now(timezone.utc))
    saved_key = _overview_key(day)

    # --- 0. Today's narrative already exists ⇒ replay it, spend nothing -------
    if not force:
        saved = await portfolio_cache.get(session, user_id, saved_key)
        if saved is not None:
            payload = dict(saved)
            payload["saved"] = True

            async def saved_stream():
                yield _sse("start", {"status": "running", "agents": [name for name, _, _ in _agent_names()]})
                yield _sse("complete", payload)

            return StreamingResponse(
                saved_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
            )

    # --- 1. Verified data → metrics (raises typed HTTP on a source failure) ---
    try:
        snapshot = await connector.fetch_snapshot(user_id)
        holdings = await _gather_holdings(connector, user_id, snapshot)
    except PortfolioSourceError as exc:
        _fail(exc)  # -> HTTPException, matches the dashboard's error contract

    sips = await _gather_sips(connector, user_id)
    history = await _history(session, user_id)
    metrics = compute_metrics(snapshot, holdings, history=history, sips=sips)
    metrics_payload = metrics_json(metrics)
    by_key = metrics_by_key(metrics)

    # --- 2. Preflight the model: no key or over budget ⇒ degrade, no spend ----
    limiter = get_limiter()
    degrade_reason: Optional[str] = None
    reserved = False
    if not _llm_configured():
        degrade_reason = "llm_unavailable"
    else:
        decision = limiter.reserve(user_id)
        if not decision.allowed:
            degrade_reason = "spend_cap"
        else:
            reserved = True

    async def event_stream():
        yield _sse("start", {"status": "running", "agents": [name for name, _, _ in _agent_names()]})

        if degrade_reason is not None:
            yield _sse("complete", _complete(metrics_payload, degraded=True, reason=degrade_reason))
            return

        narrative: list[dict[str, Any]] = []
        scripted = False
        agents_seen: list[dict[str, Any]] = []
        try:
            async for chunk in overview_stream(by_key, thread_id=user_id):
                for node, payload in chunk.items():
                    if not isinstance(payload, dict):
                        continue
                    for event in payload.get("agents", []):
                        agents_seen.append(event)
                        yield _sse("update", {"node": event.get("node", node), "status": event.get("status", "done")})
                    if "narrative" in payload:
                        narrative = payload.get("narrative") or []
                        scripted = bool(payload.get("scripted"))
        except OverviewLLMError as exc:
            # The model failed mid-run — refund the reservation and degrade.
            if reserved:
                limiter.release(user_id)
            _log.info("overview degraded: %s", exc)
            yield _sse("complete", _complete(metrics_payload, degraded=True, reason="llm_unavailable"))
            return
        except Exception as exc:  # noqa: BLE001 - never a 500 mid-stream
            if reserved:
                limiter.release(user_id)
            _log.warning("overview graph error", exc_info=True)
            yield _sse("complete", _complete(metrics_payload, degraded=True, reason="error"))
            return

        payload = _complete(
            metrics_payload,
            degraded=False,
            reason=None,
            narrative=narrative,
            scripted=scripted,
            agents=agents_seen,
        )
        # Only a clean run is saved. A degraded one returned above never reaches
        # here, so a minute without the model cannot claim the rest of the day.
        # The request-scoped session outlives the stream (FastAPI closes yield
        # dependencies after the response is sent), so this write is in time.
        await portfolio_cache.put(session, user_id, saved_key, payload)
        yield _sse("complete", payload)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


def _agent_names():
    from agents.portfolio.agents import SPECIALISTS

    return SPECIALISTS


def _complete(
    metrics_payload: list[dict[str, Any]],
    *,
    degraded: bool,
    reason: Optional[str],
    narrative: Optional[list[dict[str, Any]]] = None,
    scripted: bool = False,
    agents: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    return {
        "status": "degraded" if degraded else "complete",
        "degraded": degraded,
        "reason": reason,
        "narrative": narrative or [],
        "scripted": scripted,
        "metrics": metrics_payload,
        "agents": agents or [],
    }


__all__ = ["router"]
