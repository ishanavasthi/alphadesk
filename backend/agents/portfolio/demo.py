"""The committed `/demo` overview artifact (card A1, item 10).

U1 serves the overview at `/demo` **statically** — never an LLM call at request
time — so the narrative and metric dict are frozen into
``backend/tests/fixtures/demo/overview.json`` and served from there. This module
is the single generator of that file: it runs the real metric computation over
the StubConnector's invented portfolio and renders the **deterministic** scripted
narrative (`scripted_overview_prose`), so regenerating it needs no API spend and
is byte-reproducible in CI.

Regenerate (a manual step whenever the demo fixtures or the scripted prose
change):

    cd backend && python -m agents.portfolio.demo

The values are synthetic (stub-derived) and safe to commit. A test asserts the
committed file's metrics match a fresh computation from the fixtures, so a drift
between the two fails CI.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agents.portfolio.agents import scripted_overview_prose
from agents.portfolio.metrics import (
    compute_metrics,
    metrics_by_key,
    metrics_json,
    to_history_points,
)
from agents.portfolio.narrative import invented_figures, parse_prose
from portfolio.connectors.stub import DEMO_FIXTURES, StubConnector
from portfolio.models import AssetType

DEMO_USER = "local"
ARTIFACT_PATH = DEMO_FIXTURES / "overview.json"


async def build_demo_overview() -> dict[str, Any]:
    """Compute metrics + scripted narrative from the stub fixtures."""
    connector = StubConnector()
    snapshot = await connector.fetch_snapshot(DEMO_USER)

    holdings: list = []
    seen: set[str] = set()
    for slice_ in snapshot.by_asset_type:
        at = slice_.asset_type
        if at is None:
            continue
        key = at.value if at is not AssetType.UNKNOWN else "UNKNOWN"
        if key in seen:
            continue
        seen.add(key)
        holdings.extend(await connector.fetch_holdings(DEMO_USER, at))

    sips = await connector.fetch_sips(DEMO_USER)
    metrics = compute_metrics(snapshot, holdings, history=to_history_points([]), sips=sips)
    by_key = metrics_by_key(metrics)

    narrative = parse_prose(scripted_overview_prose(by_key), by_key)
    offenders = invented_figures(narrative, metrics)
    if offenders:  # pragma: no cover - the scripted prose cites tokens only
        raise AssertionError(f"scripted demo narrative has untraceable figures: {offenders}")

    return {
        "source": "stub",
        "generated_by": "scripted",
        "note": (
            "Synthetic demo overview. Metrics are computed from "
            "backend/tests/fixtures/demo/; the narrative is the deterministic "
            "scripted prose (no LLM). Regenerate with "
            "`python -m agents.portfolio.demo`."
        ),
        "degraded": False,
        "narrative": narrative,
        "metrics": metrics_json(metrics),
    }


def write_artifact(path: Path = ARTIFACT_PATH) -> Path:
    data = asyncio.run(build_demo_overview())
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover
    out = write_artifact()
    print(f"wrote demo overview artifact → {out}")
