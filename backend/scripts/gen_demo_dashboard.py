"""Generate the committed `/demo` dashboard fixtures (card U1).

The public `/demo` route renders the FULL portfolio dashboard for a visitor with
no IND Money account and no sign-in. Its ironclad property: **it makes no LLM
call and no authenticated backend call, ever.** So the data it draws is frozen
into a committed fixture in the frontend, and this script is what regenerates it.

What it produces (`frontend/lib/demo/dashboard.json`):

- ``summary`` — exactly what ``GET /portfolio/summary`` returns for the stub
  portfolio, serialized by the real route serializer (`_snapshot_json`), so the
  demo dashboard cannot drift from what a linked one renders.
- ``buckets`` — the per-asset-type holdings walk the dashboard performs
  (`app/portfolio/page.tsx::loadHoldings`), pre-computed. Each carries the rows
  ``GET /portfolio/holdings?asset_type=`` would return (`_holding_json`) plus the
  snapshot's reported value, so the un-enumerable EPF bucket renders its dashed
  "appears in your snapshot but no rows" callout exactly as the live dashboard
  does.
- ``overview`` — card A1's committed narrative artifact
  (`backend/tests/fixtures/demo/overview.json`), reshaped into the
  ``OverviewComplete`` event the ``AiOverview`` component consumes, with every
  agent marked done. Scripted prose, no LLM — see A1 §10.

The clock is pinned so the file is byte-reproducible: no timestamp churn on
regeneration. ``as_of`` is a fixed synthetic instant and ``last_captured_at`` is
null (the demo has no captured history — the trend renders its honest empty
state, which is the truth for a portfolio nobody has been snapshotting).

Regenerate (run from ``backend/``):

    python -m scripts.gen_demo_dashboard
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from api.routes.portfolio import _holding_json, _snapshot_json
from portfolio.connectors.stub import StubConnector
from portfolio.models import AssetType

# A fixed synthetic instant so the fixture never churns on regeneration.
_PINNED = datetime(2026, 8, 15, 4, 30, 0, tzinfo=timezone.utc)

_DEMO_USER = "demo"

_BACKEND = Path(__file__).resolve().parents[1]
_OVERVIEW_SRC = _BACKEND / "tests" / "fixtures" / "demo" / "overview.json"
_OUT = _BACKEND.parent / "frontend" / "lib" / "demo" / "dashboard.json"

_AGENTS = [
    "allocation_critic",
    "concentration_risk",
    "sip_health",
    "performance_attribution",
    "synthesizer",
]


def _num(value: str | None) -> float | None:
    return None if value in (None, "") else float(value)


async def _build() -> dict:
    connector = StubConnector(clock=lambda: _PINNED)

    health = await connector.link_health(_DEMO_USER)
    snapshot = await connector.fetch_snapshot(_DEMO_USER)
    summary = _snapshot_json(snapshot, health.value, None, _DEMO_USER)

    # Mirror app/portfolio/page.tsx::loadHoldings: one bucket per asset_type the
    # snapshot reports, UNKNOWN de-duplicated, ordered by value descending.
    wanted: dict[str, dict] = {}
    for slice_ in summary["by_asset_type"]:
        key = slice_["asset_type"]
        if not key:
            continue
        value = _num(slice_["current_value"]) or 0.0
        existing = wanted.get(key)
        if existing:
            existing["value"] += value
        else:
            wanted[key] = {"raw": slice_["asset_type_raw"], "value": value}

    ordered = sorted(wanted.items(), key=lambda kv: kv[1]["value"], reverse=True)

    buckets = []
    for key, meta in ordered:
        rows = await connector.fetch_holdings(_DEMO_USER, AssetType.coerce(key))
        buckets.append(
            {
                "assetType": key,
                "assetTypeRaw": meta["raw"],
                # ``status`` is always "ok" for the stub — it raises no source
                # errors — so the demo exercises the populated path and the EPF
                # source-empty callout (empty rows, positive reported value).
                "status": "ok",
                "reportedValue": round(meta["value"], 2) if meta["value"] else meta["value"],
                "rows": [_holding_json(h) for h in rows],
            }
        )

    overview_src = json.loads(_OVERVIEW_SRC.read_text(encoding="utf-8"))
    overview = {
        "status": "complete",
        "degraded": bool(overview_src.get("degraded", False)),
        "reason": None,
        "narrative": overview_src["narrative"],
        # A1 §10: the committed narrative is the deterministic scripted prose, not
        # a captured live run — byte-reproducible, zero spend, still a real
        # overview over real computed metrics.
        "scripted": True,
        "metrics": overview_src["metrics"],
        "agents": [{"node": node, "status": "done"} for node in _AGENTS],
    }

    return {
        "_generated_by": "backend/scripts/gen_demo_dashboard.py",
        "_note": (
            "Committed fixtures for the public /demo route (card U1). 100% "
            "synthetic (stub portfolio). No LLM, no auth, no network at request "
            "time. Regenerate with `python -m scripts.gen_demo_dashboard`."
        ),
        "summary": summary,
        "buckets": buckets,
        "overview": overview,
    }


def main() -> None:
    data = asyncio.run(_build())
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {_OUT} ({len(data['buckets'])} buckets)")


if __name__ == "__main__":
    main()
