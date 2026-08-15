"""The stub connector's own behaviour — the parts the shared contract cannot see.

The contract suite proves the stub is *interchangeable*. This file proves the
things that make it worth having: per-user portfolios (F4's isolation seam),
an injectable link health, and demo data that carries the same awkward shapes
real data does.

None of it is scaffolding-for-scaffolding: the stub is what U1's public `/demo`
route serves and what F4's cross-user tests will run against forever.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio.connectors.stub import DEMO_FIXTURES, StubConnector
from portfolio.errors import PayloadShapeError, UserScopeError
from portfolio.models import (
    AssetType,
    BreakdownBy,
    LinkHealth,
    sum_holdings_value,
)

NOW = datetime(2026, 8, 15, 6, 30, tzinfo=timezone.utc)
USER = "local"


def stub(**kwargs) -> StubConnector:
    return StubConnector(clock=lambda: NOW, **kwargs)


@pytest.fixture
def other_portfolio(tmp_path: Path) -> Path:
    """A second, deliberately different invented portfolio."""
    (tmp_path / "snapshot.json").write_text(json.dumps({
        "net_worth": 4242.0,
        "gross_value": 4242.0,
        "invested_total": 4000.0,
        "liabilities_total": 0.0,
        "by_asset_type": [
            {"label": "FD", "asset_type": "FD", "invested_amount": 4000.0,
             "current_value": 4242.0, "weight_pct": 100.0},
        ],
        "by_asset_class": [], "by_sector": [], "by_market_cap": [],
    }), encoding="utf-8")
    (tmp_path / "holdings.json").write_text(json.dumps({
        "FD": [{
            "external_id": "OTHER-FD-0001", "asset_type": "FD", "symbol": None,
            "name": "Other Demo Deposit", "isin": None, "units": None,
            "invested_amount": 4000.0, "current_value": 4242.0,
            "current_price": None,
        }],
    }), encoding="utf-8")
    (tmp_path / "allocations.json").write_text("{}", encoding="utf-8")
    (tmp_path / "sips.json").write_text('{"mf": [], "ind_stock": []}', encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------
# Per-user portfolios — F4's isolation seam
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_users_get_two_genuinely_different_portfolios(other_portfolio):
    """This is the seam F4's cross-user isolation tests will stand on. If the
    stub served one portfolio to everybody, an isolation test against it could
    never fail."""
    connector = stub(portfolios={"someone-else": other_portfolio})

    mine = await connector.fetch_holdings(USER, AssetType.FD)
    theirs = await connector.fetch_holdings("someone-else", AssetType.FD)

    assert {h.external_id for h in mine} != {h.external_id for h in theirs}
    assert {h.external_id for h in theirs} == {"OTHER-FD-0001"}
    assert "OTHER-FD-0001" not in {h.external_id for h in mine}


@pytest.mark.asyncio
async def test_the_snapshot_is_per_user_too(other_portfolio):
    connector = stub(portfolios={"someone-else": other_portfolio})
    mine = await connector.fetch_snapshot(USER)
    theirs = await connector.fetch_snapshot("someone-else")
    assert mine.net_worth != theirs.net_worth
    assert theirs.net_worth == Decimal("4242.0")


@pytest.mark.asyncio
async def test_an_unmapped_user_falls_back_to_the_public_demo(other_portfolio):
    connector = stub(portfolios={"someone-else": other_portfolio})
    anyone = await connector.fetch_snapshot("a-visitor-with-no-account")
    default = await connector.fetch_snapshot(USER)
    assert anyone.net_worth == default.net_worth


@pytest.mark.asyncio
async def test_an_empty_user_id_is_refused_before_any_file_is_read():
    with pytest.raises(UserScopeError):
        await stub().fetch_holdings("", AssetType.MF)


@pytest.mark.asyncio
async def test_a_missing_portfolio_directory_is_a_typed_error(tmp_path):
    with pytest.raises(PayloadShapeError, match="demo fixture missing"):
        await stub(default_dir=tmp_path / "nowhere").fetch_snapshot(USER)


# --------------------------------------------------------------------------
# Injected link health
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("health", list(LinkHealth))
async def test_the_injected_link_health_is_honoured(health):
    """Not decoration: it is how an isolation or UI test rehearses the
    expiring / needs-relink / revoked states without a real credential."""
    assert await stub(health=health).link_health(USER) is health


@pytest.mark.asyncio
async def test_link_health_defaults_to_linked():
    assert await stub().link_health(USER) is LinkHealth.LINKED


# --------------------------------------------------------------------------
# No shared mutable state between loads
# --------------------------------------------------------------------------

def test_the_loader_returns_a_fresh_document_every_time():
    """The demo files are read, never cached.

    Caching them would hand every caller the *same* dict as `raw`, so one
    caller annotating its copy would rewrite everybody else's — including
    across users. Asserting on the loader directly, because the model copies
    the top-level `raw` dict and would mask a cache at that level.
    """
    from portfolio.connectors import stub as stub_module

    first = stub_module._load(DEMO_FIXTURES, "holdings.json")
    second = stub_module._load(DEMO_FIXTURES, "holdings.json")
    assert first == second
    assert first is not second
    assert first["MF"] is not second["MF"], "the nested containers are shared"
    assert first["MF"][0] is not second["MF"][0]


@pytest.mark.asyncio
async def test_a_caller_cannot_corrupt_the_next_load():
    """The publicly visible half of the same property: everything reachable
    from a returned object is this caller's to scribble on."""
    connector = stub()
    first = await connector.fetch_snapshot(USER)
    second = await connector.fetch_snapshot(USER)

    # `raw` itself is copied by the model; the containers INSIDE it are what a
    # cache would share, so that is where the test has to look.
    assert first.raw["by_asset_type"] is not second.raw["by_asset_type"]

    before = len(second.raw["by_asset_type"])
    first.raw["by_asset_type"].append({"label": "INJECTED", "current_value": 1})
    third = await connector.fetch_snapshot(USER)
    assert len(third.raw["by_asset_type"]) == before
    assert len(third.by_asset_type) == len(second.by_asset_type)


@pytest.mark.asyncio
async def test_holdings_raw_survives_as_the_row_it_came_from():
    connector = stub()
    rows = await connector.fetch_holdings(USER, AssetType.MF)
    assert rows[0].raw["external_id"] == rows[0].external_id


# --------------------------------------------------------------------------
# The demo portfolio keeps the shapes that make the model necessary
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_demo_portfolio_carries_every_edge_case_it_claims_to():
    connector = stub()
    rows = []
    for asset_type in AssetType.queryable():
        rows.extend(await connector.fetch_holdings(USER, asset_type))
    rows.extend(await connector.fetch_holdings(USER, AssetType.UNKNOWN))

    unknown_basis = [r for r in rows if r.invested_amount is None]
    assert len(unknown_basis) >= 2, "the 0 and absent-key encodings both matter"
    assert all(r.pnl is None and r.pnl_pct is None for r in unknown_basis)

    worthless = [r for r in rows if r.current_value == 0]
    assert len(worthless) == 1
    assert worthless[0].pnl_pct == Decimal("-100.00")

    cash_like = [r for r in rows if r.units is None and r.current_value > 0]
    assert cash_like, "value must never be derivable as units x price"


@pytest.mark.asyncio
async def test_the_stub_enumerates_its_out_of_enum_bucket():
    """Unlike IND Money, the stub CAN list a bucket outside the 16 — which is
    what makes the UNKNOWN path testable at all."""
    rows = await stub().fetch_holdings(USER, AssetType.UNKNOWN)
    assert rows
    assert all(r.asset_type is AssetType.UNKNOWN for r in rows)
    assert all(r.asset_type_raw == "US_STOCK_WALLET" for r in rows)


@pytest.mark.asyncio
async def test_an_out_of_enum_allocation_is_empty_rather_than_an_error():
    allocation = await stub().fetch_allocation(USER, AssetType.UNKNOWN, BreakdownBy.SECTOR)
    assert allocation.slices == []


@pytest.mark.asyncio
async def test_the_holdings_sum_does_not_equal_the_snapshot_total():
    """The demo data reproduces the real reconciliation gap on purpose: `EPF`
    is a snapshot bucket with no holdings rows. A stub that balanced perfectly
    would let a reconciliation bug ship."""
    connector = stub()
    rows = []
    for asset_type in AssetType.queryable():
        rows.extend(await connector.fetch_holdings(USER, asset_type))
    snapshot = await connector.fetch_snapshot(USER)
    assert rows
    assert sum_holdings_value(rows) != snapshot.gross_value


def test_the_demo_fixtures_ship_with_the_package():
    assert DEMO_FIXTURES.is_dir()
    for name in ("snapshot.json", "holdings.json", "allocations.json", "sips.json"):
        assert (DEMO_FIXTURES / name).is_file(), name
