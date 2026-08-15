"""One contract suite, run against every connector.

This is the file that makes the seam real: if `StubConnector` and
`IndMoneyConnector` are not genuinely interchangeable, something here fails.
Every future source (and F3's per-user variant) joins by adding one line to
`CONNECTORS`.

Nothing here reaches the network — the IND Money case is driven by the C2
synthetic fixtures through an injected transport.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from portfolio.connectors.base import PortfolioConnector
from portfolio.connectors.ind_money import IndMoneyConnector
from portfolio.connectors.stub import StubConnector
from portfolio.errors import PortfolioSourceError, UnsupportedAssetType
from portfolio.models import (
    Allocation,
    AssetType,
    BreakdownBy,
    Holding,
    LinkHealth,
    PortfolioSnapshot,
    Sip,
    sum_holdings_value,
)
from tests.ind_money_transport import FixtureTransport

USER = "local"
NOW = datetime(2026, 8, 15, 6, 30, tzinfo=timezone.utc)


async def _sleep(_seconds: float) -> None:
    return None


async def _linked() -> dict:
    return {"authenticated": True, "expires_in_sec": 3000}


def _stub() -> PortfolioConnector:
    return StubConnector(clock=lambda: NOW)


def _ind_money() -> PortfolioConnector:
    return IndMoneyConnector(
        transport=FixtureTransport(), clock=lambda: NOW, sleep=_sleep,
        auth_status=_linked,
    )


CONNECTORS = {"stub": _stub, "ind_money": _ind_money}

#: How each source answers for an asset type outside the 16-value enum. This is
#: a real, documented divergence, not an escape hatch: the stub can enumerate
#: its own non-standard buckets and IND Money cannot (no call accepts a value
#: outside its enum). Asserting it per-connector is what stops one
#: implementation from quietly skipping a check the other has to pass.
UNKNOWN_ASSET_TYPE_BEHAVIOUR = {"stub": "enumerates", "ind_money": "refuses"}


@pytest.fixture(params=sorted(CONNECTORS))
def connector_case(request) -> tuple[str, PortfolioConnector]:
    return request.param, CONNECTORS[request.param]()


@pytest.fixture
def connector(connector_case) -> PortfolioConnector:
    return connector_case[1]


async def all_holdings(connector: PortfolioConnector) -> list[Holding]:
    """Every queryable asset type, one call each.

    ⚠️ Do **not** copy this against a live source. Sixteen calls to a single
    tool is precisely the single-tool burst that trips IND Money's per-tool
    limit (15/min) first. It is safe here only because both connectors are
    offline: the stub reads files and the IND Money case is driven by fixtures.
    """
    rows: list[Holding] = []
    for asset_type in AssetType.queryable():
        rows.extend(await connector.fetch_holdings(USER, asset_type))
    return rows


# --------------------------------------------------------------------------
# The interface itself
# --------------------------------------------------------------------------

def test_every_connector_implements_the_whole_interface(connector):
    assert isinstance(connector, PortfolioConnector)
    assert isinstance(connector.source, str) and connector.source
    for name in sorted(PortfolioConnector.__abstractmethods__):
        method = getattr(type(connector), name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"
        # Every method takes an explicit user_id, from its very first line.
        assert list(inspect.signature(method).parameters)[1] == "user_id", name


def test_there_is_more_than_one_real_implementation():
    """A one-implementation 'interface' is a rename, not a seam."""
    assert len(CONNECTORS) >= 2
    assert len({factory().source for factory in CONNECTORS.values()}) == len(CONNECTORS)


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_is_typed_stamped_and_inr(connector):
    snapshot = await connector.fetch_snapshot(USER)
    assert isinstance(snapshot, PortfolioSnapshot)
    assert snapshot.source == connector.source
    assert isinstance(snapshot.net_worth, Decimal)
    assert snapshot.currency == "INR"
    assert snapshot.as_of.tzinfo is timezone.utc  # stamped, never parsed


# --------------------------------------------------------------------------
# Holdings
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_asset_type_returns_typed_rows_or_an_empty_list(connector):
    for asset_type in AssetType.queryable():
        rows = await connector.fetch_holdings(USER, asset_type)
        assert isinstance(rows, list)
        for row in rows:
            assert isinstance(row, Holding)
            assert row.source == connector.source
            assert row.currency == "INR"
            assert row.as_of.tzinfo is timezone.utc
            assert isinstance(row.current_value, Decimal)


@pytest.mark.asyncio
async def test_the_portfolio_is_not_empty(connector):
    """Otherwise every assertion below is vacuously true."""
    assert len(await all_holdings(connector)) >= 3


@pytest.mark.asyncio
async def test_an_asset_type_with_nothing_in_it_returns_an_empty_list(connector):
    assert await connector.fetch_holdings(USER, AssetType.VEHICLE) == []


@pytest.mark.asyncio
async def test_identity_is_unique_within_a_source(connector):
    rows = await all_holdings(connector)
    ids = [(row.source, row.external_id) for row in rows]
    assert len(set(ids)) == len(ids)


@pytest.mark.asyncio
async def test_unknown_cost_basis_never_produces_a_number(connector):
    """Both portfolios carry such a row on purpose."""
    unknown = [row for row in await all_holdings(connector) if row.invested_amount is None]
    assert unknown, "the fixture lost its unknown-cost-basis row"
    for row in unknown:
        assert row.pnl is None
        assert row.pnl_pct is None


@pytest.mark.asyncio
async def test_a_known_cost_basis_produces_a_consistent_pnl(connector):
    for row in await all_holdings(connector):
        if row.invested_amount is None or row.pnl is None:
            continue
        assert row.current_value - row.invested_amount == pytest.approx(
            float(row.pnl), abs=0.01
        )


@pytest.mark.asyncio
async def test_an_asset_type_outside_the_enum_behaves_as_documented(connector_case):
    """A source either enumerates its non-standard buckets or says it cannot —
    and **which** it does is pinned per connector.

    An earlier version swallowed `UnsupportedAssetType` and returned early,
    which meant IND Money silently skipped every assertion the stub had to
    pass. A contract test that one implementation can opt out of is not a
    contract test.
    """
    name, connector = connector_case
    behaviour = UNKNOWN_ASSET_TYPE_BEHAVIOUR[name]

    if behaviour == "refuses":
        with pytest.raises(UnsupportedAssetType):
            await connector.fetch_holdings(USER, AssetType.UNKNOWN)
        return

    rows = await connector.fetch_holdings(USER, AssetType.UNKNOWN)
    assert rows, "a source that claims to enumerate them must return some"
    assert all(row.asset_type is AssetType.UNKNOWN for row in rows)
    assert all(row.asset_type_raw for row in rows), "the original string is lost"


@pytest.mark.asyncio
@pytest.mark.parametrize("by", list(BreakdownBy))
async def test_an_out_of_enum_allocation_behaves_as_documented(connector_case, by):
    """The same divergence, on the allocation path — which has its own guard
    and would otherwise go entirely untested."""
    name, connector = connector_case
    if UNKNOWN_ASSET_TYPE_BEHAVIOUR[name] == "refuses":
        with pytest.raises(UnsupportedAssetType):
            await connector.fetch_allocation(USER, AssetType.UNKNOWN, by)
    else:
        allocation = await connector.fetch_allocation(USER, AssetType.UNKNOWN, by)
        assert allocation.asset_type is AssetType.UNKNOWN


def test_every_connector_declares_its_out_of_enum_behaviour():
    """Adding a source without saying which way it goes is not allowed."""
    assert set(UNKNOWN_ASSET_TYPE_BEHAVIOUR) == set(CONNECTORS)
    assert set(UNKNOWN_ASSET_TYPE_BEHAVIOUR.values()) == {"enumerates", "refuses"}, (
        "if every source behaved the same way, this would not need to be a map"
    )


# --------------------------------------------------------------------------
# Allocation, SIPs, link health
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("by", list(BreakdownBy))
async def test_allocation_echoes_the_request_and_returns_typed_slices(connector, by):
    allocation = await connector.fetch_allocation(USER, AssetType.MF, by)
    assert isinstance(allocation, Allocation)
    assert allocation.source == connector.source
    assert allocation.asset_type is AssetType.MF
    assert allocation.by is by
    assert allocation.currency == "INR"
    for slice_ in allocation.slices:
        assert isinstance(slice_.current_value, Decimal)


@pytest.mark.asyncio
async def test_an_empty_allocation_combination_is_not_an_error(connector):
    allocation = await connector.fetch_allocation(USER, AssetType.PPF, BreakdownBy.SECTOR)
    assert allocation.slices == []


@pytest.mark.asyncio
async def test_sips_are_typed(connector):
    sips = await connector.fetch_sips(USER)
    assert isinstance(sips, list)
    for sip in sips:
        assert isinstance(sip, Sip)
        assert sip.source == connector.source
        assert sip.as_of.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_link_health_is_one_of_the_four_states(connector):
    assert await connector.link_health(USER) in set(LinkHealth)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("fetch_snapshot", ()),
    ("fetch_holdings", (AssetType.MF,)),
    ("fetch_allocation", (AssetType.MF, BreakdownBy.SECTOR)),
    ("fetch_sips", ()),
    ("link_health", ()),
])
async def test_no_method_accepts_an_empty_user_id(connector, method, args):
    """`user_id` is explicit from the first line every one of these was written,
    so that F3 does not have to retrofit it into a shipped data path."""
    with pytest.raises(PortfolioSourceError):
        await getattr(connector, method)("", *args)
