"""A fake IND Money transport backed by the C2 synthetic fixtures.

Not a test module (pytest does not collect it) — a helper both the connector
tests and the shared contract suite import, so they exercise the *same* payloads
the spike verified rather than each inventing their own.

The fixtures mirror the payload **after** `tools.ind_money._unwrap`, which is
exactly what the connector's transport contract promises, so this stands in for
the real transport without faking the MCP session.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ind_money"

#: Which fixture answers `networth_holdings(asset_type=…)`.
HOLDINGS_FIXTURES = {
    "MF": "networth_holdings__MF.json",
    "US_STOCK": "networth_holdings__US_STOCK.json",
    "IND_STOCK": "networth_holdings__IND_STOCK__populated.UNVERIFIED.json",
}
#: Every other asset type: the account holds nothing in it.
EMPTY_HOLDINGS = "networth_holdings__empty_asset_type.json"

BREAKDOWN_FIXTURES = {
    ("MF", "assets"): "networth_allocation_breakdown__MF__assets.json",
    ("MF", "sector"): "networth_allocation_breakdown__MF__sector.json",
    ("MF", "market_cap"): "networth_allocation_breakdown__MF__market_cap.json",
}


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FixtureTransport:
    """Answers tool calls from the committed fixtures, and records every call.

    ``queue`` is a list of payloads returned (and consumed) before the fixture
    router runs — that is how a throttled response is injected ahead of a good
    one.
    """

    def __init__(self, queue: Optional[list] = None) -> None:
        self.queue = list(queue or [])
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, tool: str, arguments: Optional[dict] = None) -> Any:
        args = dict(arguments or {})
        self.calls.append((tool, args))
        if self.queue:
            return self.queue.pop(0)
        return self.route(tool, args)

    def route(self, tool: str, args: dict) -> Any:
        if tool == "networth_snapshot":
            return load("networth_snapshot.json")
        if tool == "networth_holdings":
            return load(HOLDINGS_FIXTURES.get(args.get("asset_type"), EMPTY_HOLDINGS))
        if tool == "networth_allocation_breakdown":
            key = (args.get("asset_type"), args.get("breakdown_by"))
            name = BREAKDOWN_FIXTURES.get(key)
            if name:
                return load(name)
            # Most of the 16×3 grid is empty; the echo keys still come back.
            return {
                "asset_type": args.get("asset_type"),
                "breakdown_by": args.get("breakdown_by"),
                "data": [],
            }
        if tool == "mf_sips":
            return load("mf_sips__empty.json")
        if tool == "indian_stocks_sips":
            return load("indian_stocks_sips__empty.json")
        raise AssertionError(f"unexpected tool call: {tool}")


__all__ = [
    "BREAKDOWN_FIXTURES",
    "EMPTY_HOLDINGS",
    "FIXTURES",
    "FixtureTransport",
    "HOLDINGS_FIXTURES",
    "load",
]
