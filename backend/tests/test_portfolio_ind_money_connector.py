"""The IND Money connector, against the C2 synthetic fixtures.

Everything asserted here traces back to a specific finding in
`docs/ind_money_payloads.md`; the section is named in each test's docstring so a
future reader can check the claim rather than trust it.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from portfolio.connectors.ind_money import IndMoneyConnector
from portfolio.errors import (
    NonInrValue,
    NotLinked,
    PayloadShapeError,
    PortfolioSourceError,
    RateLimited,
    SourceReportedError,
    SourceUnavailable,
    UnsupportedAssetType,
    UnverifiedShapeError,
    UserScopeError,
)
from portfolio.models import (
    AssetType,
    BreakdownBy,
    Holding,
    LinkHealth,
    sum_holdings_value,
)
from tests.ind_money_transport import FixtureTransport, load

NOW = datetime(2026, 8, 15, 6, 30, tzinfo=timezone.utc)
USER = "local"


class Sleeper:
    """Records backoff instead of spending it."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def connector(transport=None, **kwargs) -> IndMoneyConnector:
    return IndMoneyConnector(
        transport=transport or FixtureTransport(),
        clock=lambda: NOW,
        sleep=Sleeper(),
        auth_status=_status(authenticated=True, expires_in_sec=3000),
        **kwargs,
    )


def _status(**payload):
    async def status() -> dict:
        return dict(payload)

    return status


def one_shot(payload):
    """A transport that returns `payload` for every call."""

    async def transport(tool: str, arguments=None):
        return payload

    return transport


def raising(exc: BaseException):
    """A transport that fails the way a real client library fails."""

    async def transport(tool: str, arguments=None):
        raise exc

    return transport


def mf_rows(*rows: dict) -> dict:
    """A holdings payload built from full-shape rows, edited per test."""
    return {"holdings": list(rows)}


def mf_row(**overrides) -> dict:
    row = {
        "asset_type": "MF", "assetclass_l2": "Fixture Growth Assets",
        "market_cap": "Fixture Cap Band A", "investment": "Fixture Alpha Fund",
        "investment_code": "FIXT000901", "broker": "FIXBRK01",
        "invested_amount": 100000.0, "market_value": 110000.0,
        "total_units": 1000.0, "unit_price": 110.0, "total_pnl": 10000.0,
        "pnl_per": 10.0, "holding_percent": 11.0, "xirr": 0,
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------
# Transport contract: the wire format is a stringified-JSON envelope
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_connector_consumes_what_unwrap_produces():
    """§1: every tool answers `{"result": "<stringified JSON>"}`; the connector
    sits on top of `tools.ind_money._unwrap`, it does not re-implement it."""
    from tools.ind_money import _unwrap

    raw = load("raw_mcp_envelope__networth_snapshot.json")
    snapshot = await connector(one_shot(_unwrap(raw))).fetch_snapshot(USER)
    assert snapshot.net_worth > 0


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_totals_are_passed_through_untouched():
    """Q3: store the vendor's own total; never recompute it from holdings."""
    payload = load("networth_snapshot.json")
    snapshot = await connector().fetch_snapshot(USER)

    assert snapshot.net_worth == Decimal(str(payload["total_networth"]))
    assert snapshot.gross_value == Decimal(str(payload["total_current_value"]))
    assert snapshot.invested_total == Decimal(str(payload["total_invested"]))
    assert snapshot.liabilities_total == Decimal(str(payload["liabilities"]["total"]))
    assert snapshot.currency == "INR"
    assert snapshot.as_of == NOW


@pytest.mark.asyncio
async def test_snapshot_carries_all_four_breakdowns():
    snapshot = await connector().fetch_snapshot(USER)
    assert len(snapshot.by_asset_type) == 5
    assert len(snapshot.by_asset_class) == 4
    assert len(snapshot.by_sector) == 3
    assert len(snapshot.by_market_cap) == 3
    assert all(s.label for s in snapshot.by_sector)


@pytest.mark.asyncio
async def test_the_unenumerable_bucket_survives_as_unknown():
    """Q3: the snapshot reports a bucket the holdings enum does not accept. It
    must land in the totals, tagged UNKNOWN, with its original string intact."""
    snapshot = await connector().fetch_snapshot(USER)
    wallet = [s for s in snapshot.by_asset_type if s.asset_type_raw == "US_STOCK_WALLET"]
    assert len(wallet) == 1
    assert wallet[0].asset_type is AssetType.UNKNOWN
    assert wallet[0].current_value > 0
    # ... and it is recognisably US exposure despite being outside the enum.
    assert {s.label for s in snapshot.us_exposure_slices()} == {"US_STOCK", "US_STOCK_WALLET"}


@pytest.mark.asyncio
async def test_snapshot_needs_a_total_and_says_so_when_it_is_missing():
    payload = load("networth_snapshot.json")
    payload.pop("total_networth")
    with pytest.raises(PayloadShapeError, match="total_networth"):
        await connector(one_shot(payload)).fetch_snapshot(USER)


@pytest.mark.asyncio
async def test_an_empty_portfolio_is_not_an_error():
    snapshot = await connector(one_shot(load("networth_snapshot__empty.json"))).fetch_snapshot(USER)
    assert snapshot.net_worth == 0
    assert snapshot.by_asset_type == []


# --------------------------------------------------------------------------
# Holdings — the aggregator shape and its edge cases
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdings_map_to_typed_rows():
    holdings = await connector().fetch_holdings(USER, AssetType.MF)
    assert len(holdings) == 6
    assert all(isinstance(h, Holding) for h in holdings)
    assert all(h.source == "ind_money" for h in holdings)
    assert all(h.asset_type is AssetType.MF for h in holdings)
    assert all(h.currency == "INR" for h in holdings)
    assert all(h.as_of == NOW for h in holdings)
    assert all(isinstance(h.current_value, Decimal) for h in holdings)


@pytest.mark.asyncio
async def test_missing_zero_and_null_cost_basis_all_degrade_to_none():
    """Q2: the vendor returns 0 (or nothing) when a linked broker withholds the
    invested amount. Three encodings, one meaning: unknown."""
    holdings = await connector().fetch_holdings(USER, AssetType.MF)
    unknown = [h for h in holdings if h.invested_amount is None]
    assert len(unknown) == 3  # key absent, 0, and null
    for h in unknown:
        assert h.pnl is None and h.pnl_pct is None
        assert h.avg_cost is None
        assert h.current_value > 0  # the value itself is still known


@pytest.mark.asyncio
async def test_a_worthless_holding_keeps_its_real_minus_100():
    """The zero-*value* row has a real cost basis, so -100% is the truth."""
    holdings = await connector().fetch_holdings(USER, AssetType.MF)
    worthless = [h for h in holdings if h.current_value == 0]
    assert len(worthless) == 1
    assert worthless[0].invested_amount == Decimal("15000")
    assert worthless[0].pnl_pct == Decimal("-100.0")


@pytest.mark.asyncio
async def test_int_typed_rows_become_decimals_like_every_other_row():
    """§2.2: one fixture row types every number as `int` on purpose."""
    holdings = await connector().fetch_holdings(USER, AssetType.MF)
    integral = [h for h in holdings if h.raw.get("investment_code") == "FIXT000106"]
    assert len(integral) == 1
    assert integral[0].current_value == Decimal("30000")
    assert isinstance(integral[0].current_value, Decimal)


@pytest.mark.asyncio
async def test_value_is_never_derived_from_units_times_price():
    """Q3: cash-like rows carry units and price of exactly 0 beside a real
    value, so units × price silently yields 0 for every deposit row."""
    payload = {
        "holdings": [{
            "asset_type": "FD", "assetclass_l2": "", "market_cap": "",
            "investment": "Fixture Deposit", "investment_code": "FIXT000701",
            "broker": "", "invested_amount": 100000.0, "market_value": 108000.0,
            "total_units": 0.0, "unit_price": 0.0, "total_pnl": 8000.0,
            "pnl_per": 8.0, "holding_percent": 10.8, "xirr": 0,
        }]
    }
    holding = (await connector(one_shot(payload)).fetch_holdings(USER, AssetType.FD))[0]
    assert holding.current_value == Decimal("108000.0")
    # No unit/price decomposition exists for such a row; 0 would read as a price.
    assert holding.units is None
    assert holding.current_price is None


@pytest.mark.asyncio
async def test_empty_asset_types_return_an_empty_list_not_an_error():
    """§2.2: 11 of 16 asset types answered `{"holdings": []}`."""
    assert await connector().fetch_holdings(USER, AssetType.BOND) == []


@pytest.mark.asyncio
async def test_holdings_identity_is_source_plus_external_id():
    holdings = await connector().fetch_holdings(USER, AssetType.MF)
    ids = [h.external_id for h in holdings]
    assert len(set(ids)) == len(ids)
    assert all(h.external_id.startswith("MF:") for h in holdings)


@pytest.mark.asyncio
async def test_an_empty_instrument_code_falls_back_to_a_stable_hash():
    payload = copy.deepcopy(load("networth_holdings__MF.json"))
    payload["holdings"] = payload["holdings"][:1]
    payload["holdings"][0]["investment_code"] = ""
    first = (await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF))[0]
    second = (await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF))[0]
    assert first.external_id == second.external_id
    assert first.external_id.startswith("MF:h:")


@pytest.mark.asyncio
async def test_an_empty_display_name_becomes_none_rather_than_an_empty_label():
    """Q2: `investment` was an empty string in 1 of 14 real rows."""
    holdings = await connector().fetch_holdings(USER, AssetType.MF)
    assert any(h.name is None for h in holdings)
    assert all(h.name != "" for h in holdings)


@pytest.mark.asyncio
async def test_us_stock_rows_are_flagged_by_asset_type_alone():
    """Q4: there is no currency field to read; the asset type is the signal."""
    holdings = await connector().fetch_holdings(USER, AssetType.US_STOCK)
    assert len(holdings) == 1
    assert holdings[0].is_us_exposure
    assert holdings[0].currency == "INR"  # the source converts; we say so once


# --------------------------------------------------------------------------
# The UNVERIFIED IND_STOCK boundary
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ind_stock_empty_live_trading_envelope_maps_to_no_rows():
    """§2.2 Shape B: 19 keys, none shared with Shape A beyond `holdings`."""
    payload = load("networth_holdings__IND_STOCK__empty.json")
    assert len(payload) == 19  # guard: this is the envelope, not the plain shape
    assert await connector(one_shot(payload)).fetch_holdings(USER, AssetType.IND_STOCK) == []


@pytest.mark.asyncio
async def test_ind_stock_rows_map_when_they_match_the_documented_shape():
    holdings = await connector().fetch_holdings(USER, AssetType.IND_STOCK)
    assert len(holdings) == 2
    assert all(h.asset_type is AssetType.IND_STOCK for h in holdings)


@pytest.mark.asyncio
async def test_an_unexpected_ind_stock_key_fails_loud_and_typed():
    """No populated IND_STOCK row has ever been observed. A deviation is
    reported, never coerced into a plausible-looking model."""
    payload = copy.deepcopy(load("networth_holdings__IND_STOCK__populated.UNVERIFIED.json"))
    payload["holdings"][0]["quantity_available_for_pledge"] = 100
    with pytest.raises(UnverifiedShapeError, match="UNVERIFIED"):
        await connector(one_shot(payload)).fetch_holdings(USER, AssetType.IND_STOCK)


@pytest.mark.asyncio
async def test_a_missing_ind_stock_value_fails_loud_and_typed():
    payload = copy.deepcopy(load("networth_holdings__IND_STOCK__populated.UNVERIFIED.json"))
    payload["holdings"][0].pop("market_value")
    with pytest.raises(UnverifiedShapeError):
        await connector(one_shot(payload)).fetch_holdings(USER, AssetType.IND_STOCK)


@pytest.mark.asyncio
async def test_other_asset_types_tolerate_a_new_key_instead_of_crashing():
    """The strict boundary is IND_STOCK-only: a verified shape gaining a field
    is a vendor addition, not a broken assumption."""
    payload = copy.deepcopy(load("networth_holdings__MF.json"))
    payload["holdings"][0]["some_new_vendor_field"] = 1
    holdings = await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF)
    assert len(holdings) == 6
    assert holdings[0].raw["some_new_vendor_field"] == 1


@pytest.mark.asyncio
async def test_unknown_asset_type_cannot_be_queried_for_holdings():
    """Q3: `US_STOCK_WALLET` is reported by the snapshot and accepted by no
    holdings call — an unfetchable bucket, not a fetch that returns nothing."""
    with pytest.raises(UnsupportedAssetType, match="enum"):
        await connector().fetch_holdings(USER, AssetType.UNKNOWN)


# --------------------------------------------------------------------------
# Allocation — lazy, one slice at a time
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_allocation_returns_typed_slices():
    transport = FixtureTransport()
    allocation = await connector(transport).fetch_allocation(
        USER, AssetType.MF, BreakdownBy.ASSETS
    )
    assert allocation.asset_type is AssetType.MF
    assert allocation.by is BreakdownBy.ASSETS
    assert len(allocation.slices) == 2
    assert all(isinstance(s.current_value, Decimal) for s in allocation.slices)


@pytest.mark.asyncio
async def test_one_allocation_request_costs_exactly_one_call():
    """§2.5: the full 16×3 grid is 48 calls at cost 2 each — 96 units against a
    15/min per-tool budget, i.e. throttled after 7. Allocation is fetched
    lazily, per requested slice, and never swept."""
    transport = FixtureTransport()
    await connector(transport).fetch_allocation(USER, AssetType.MF, BreakdownBy.SECTOR)
    assert len(transport.calls) == 1
    assert transport.calls[0][0] == "networth_allocation_breakdown"


@pytest.mark.asyncio
async def test_an_empty_slice_is_a_valid_answer():
    """40 of 48 combinations returned an empty `data` list."""
    allocation = await connector().fetch_allocation(USER, AssetType.PPF, BreakdownBy.SECTOR)
    assert allocation.slices == []


@pytest.mark.asyncio
async def test_a_mismatched_echo_is_refused():
    """The payload echoes the request; attributing one slice's rows to another
    would silently mislabel an allocation chart."""
    payload = load("networth_allocation_breakdown__MF__assets.json")
    with pytest.raises(PayloadShapeError, match="echo"):
        await connector(one_shot(payload)).fetch_allocation(
            USER, AssetType.FD, BreakdownBy.ASSETS
        )


# --------------------------------------------------------------------------
# Rate limiting — the failure mode that looks like success
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_throttled_call_is_retried_after_the_servers_own_delay():
    """§2.5: `retry_after_seconds` is the only quantitative recovery signal."""
    throttle = load("rate_limit_error__tool_scope.json")
    transport = FixtureTransport(queue=[throttle])
    sleeper = Sleeper()
    c = IndMoneyConnector(
        transport=transport, clock=lambda: NOW, sleep=sleeper,
        auth_status=_status(authenticated=True, expires_in_sec=3000),
    )
    allocation = await c.fetch_allocation(USER, AssetType.MF, BreakdownBy.ASSETS)
    assert len(allocation.slices) == 2
    assert sleeper.waits == [throttle["retry_after_seconds"]]
    assert len(transport.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", [
    "rate_limit_error__tool_scope.json",
    "rate_limit_error__global_scope.UNVERIFIED.json",
])
async def test_persistent_throttling_raises_a_typed_error_carrying_the_body(fixture):
    """Both tiers. The limits are read off the body, never hard-coded — a
    client that only understands the global tier misreads a per-tool breach."""
    body = load(fixture)
    transport = FixtureTransport(queue=[body, body, body, body])
    sleeper = Sleeper()
    c = IndMoneyConnector(
        transport=transport, clock=lambda: NOW, sleep=sleeper, max_retries=2,
        auth_status=_status(authenticated=True, expires_in_sec=3000),
    )
    with pytest.raises(RateLimited) as excinfo:
        await c.fetch_holdings(USER, AssetType.MF)

    error = excinfo.value
    assert error.scope == body["scope"]
    assert error.window == body["window"]
    assert error.limit == body["limit"]
    assert error.current == body["current"]
    assert error.cost == body["cost"]
    assert error.retry_after == body["retry_after_seconds"]
    assert len(transport.calls) == 3  # initial + 2 bounded retries
    assert len(sleeper.waits) == 2


@pytest.mark.asyncio
async def test_backoff_is_capped_so_a_hostile_delay_cannot_hang_the_caller():
    body = dict(load("rate_limit_error__tool_scope.json"), retry_after_seconds=86400)
    transport = FixtureTransport(queue=[body])
    sleeper = Sleeper()
    c = IndMoneyConnector(
        transport=transport, clock=lambda: NOW, sleep=sleeper,
        max_retry_wait_seconds=30,
        auth_status=_status(authenticated=True, expires_in_sec=3000),
    )
    await c.fetch_holdings(USER, AssetType.MF)
    assert sleeper.waits == [30]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("fetch_snapshot", ()),
    ("fetch_holdings", (AssetType.MF,)),
    ("fetch_allocation", (AssetType.MF, BreakdownBy.SECTOR)),
    ("fetch_sips", ()),
])
async def test_a_throttled_body_never_reaches_the_payload_parser(method, args):
    """§2.5: the error body REPLACES the payload, so `payload["data"]` would
    raise KeyError. Every entry point checks `error` first."""
    body = load("rate_limit_error__tool_scope.json")
    c = IndMoneyConnector(
        transport=one_shot(body), clock=lambda: NOW, sleep=Sleeper(), max_retries=0,
        auth_status=_status(authenticated=True, expires_in_sec=3000),
    )
    with pytest.raises(RateLimited):
        await getattr(c, method)(USER, *args)


@pytest.mark.asyncio
async def test_a_non_rate_limit_error_body_is_also_typed():
    body = {"error": "internal_error", "message": "Fixture failure"}
    with pytest.raises(SourceReportedError) as excinfo:
        await connector(one_shot(body)).fetch_snapshot(USER)
    assert excinfo.value.code == "internal_error"
    assert not isinstance(excinfo.value, RateLimited)


@pytest.mark.asyncio
async def test_a_missing_payload_key_is_a_typed_error_not_a_keyerror():
    with pytest.raises(PayloadShapeError):
        await connector(one_shot({"unexpected": True})).fetch_holdings(USER, AssetType.MF)


@pytest.mark.asyncio
async def test_a_non_object_payload_is_a_typed_error():
    with pytest.raises(PayloadShapeError):
        await connector(one_shot(["not", "an", "object"])).fetch_snapshot(USER)


# --------------------------------------------------------------------------
# Currency stance — assert, do not assume
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_non_inr_currency_anywhere_in_a_payload_raises():
    """Q4: no payload carries a currency field today. If one ever appears and
    disagrees, v2's whole INR stance is falsified — stop, do not sum."""
    payload = copy.deepcopy(load("networth_holdings__MF.json"))
    payload["holdings"][0]["currency"] = "USD"
    with pytest.raises(NonInrValue, match="INR"):
        await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF)


@pytest.mark.asyncio
async def test_a_nested_non_inr_currency_is_found_too():
    payload = copy.deepcopy(load("networth_snapshot.json"))
    payload["liabilities"]["currency"] = "usd"
    with pytest.raises(NonInrValue) as excinfo:
        await connector(one_shot(payload)).fetch_snapshot(USER)
    assert excinfo.value.path == "liabilities.currency"


@pytest.mark.asyncio
async def test_an_inr_currency_field_confirms_the_assumption_and_passes():
    payload = copy.deepcopy(load("networth_snapshot.json"))
    payload["currency"] = "INR"
    snapshot = await connector(one_shot(payload)).fetch_snapshot(USER)
    assert snapshot.currency == "INR"


# --------------------------------------------------------------------------
# SIPs
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_both_sip_endpoints_are_read_and_empty_is_normal():
    """§2.4: both returned zero rows; the populated row shape is unverified."""
    transport = FixtureTransport()
    assert await connector(transport).fetch_sips(USER) == []
    assert [c[0] for c in transport.calls] == ["mf_sips", "indian_stocks_sips"]


@pytest.mark.asyncio
async def test_a_populated_sip_row_is_mapped_defensively():
    payload = {"mf_sips": [{
        "sip_id": "FIXSIP01", "fund_name": "Fixture Alpha Bluechip Fund",
        "sip_amount": 5125, "frequency": "monthly", "status": "active",
        "next_execution_date": "2099-01-05", "unmapped_vendor_field": 7,
    }]}

    async def transport(tool, arguments=None):
        return payload if tool == "mf_sips" else {"indian_stocks_sips": []}

    sips = await connector(transport).fetch_sips(USER)
    assert len(sips) == 1
    assert sips[0].external_id == "mf:FIXSIP01"
    assert sips[0].amount == Decimal("5125")
    assert sips[0].next_execution_at.tzinfo is not None
    # Anything unmapped survives in raw rather than being dropped or guessed at.
    assert sips[0].raw["unmapped_vendor_field"] == 7


# --------------------------------------------------------------------------
# User scoping and link health
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("fetch_snapshot", ()),
    ("fetch_holdings", (AssetType.MF,)),
    ("fetch_allocation", (AssetType.MF, BreakdownBy.SECTOR)),
    ("fetch_sips", ()),
    ("link_health", ()),
])
async def test_a_connector_refuses_a_user_it_is_not_bound_to(method, args):
    """One process, one credential set. Serving a second user off it would be a
    cross-user leak, so it is a hard error until F3 adds per-user links."""
    transport = FixtureTransport()
    with pytest.raises(UserScopeError):
        await getattr(connector(transport), method)("somebody-else", *args)
    assert transport.calls == []  # refused before any network call


@pytest.mark.asyncio
async def test_an_empty_user_id_is_refused():
    with pytest.raises(UserScopeError):
        await connector().fetch_snapshot("")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [
    ({"authenticated": True, "expires_in_sec": 3000}, LinkHealth.LINKED),
    ({"authenticated": True, "expires_in_sec": 120}, LinkHealth.EXPIRING),
    ({"authenticated": True, "expires_in_sec": None}, LinkHealth.LINKED),
    ({"authenticated": False, "expires_in_sec": None}, LinkHealth.NEEDS_RELINK),
])
async def test_link_health_reads_the_tokens_observed_state(status, expected):
    c = IndMoneyConnector(
        transport=FixtureTransport(), clock=lambda: NOW, sleep=Sleeper(),
        auth_status=_status(**status),
    )
    assert await c.link_health(USER) is expected


@pytest.mark.asyncio
async def test_a_definitive_rejection_is_revoked_not_merely_unlinked():
    """A source may not support refresh at all, so 'we hold a refresh token' is
    never evidence of health — only what the source says is."""
    from tools.ind_money_auth import MCPAuthInvalid

    async def rejecting() -> dict:
        raise MCPAuthInvalid("refresh rejected")

    c = IndMoneyConnector(
        transport=FixtureTransport(), clock=lambda: NOW, sleep=Sleeper(),
        auth_status=rejecting,
    )
    assert await c.link_health(USER) is LinkHealth.REVOKED
    # Sticky: once the grant is dead, a later transient answer cannot undo it.
    c._auth_status = _status(authenticated=True, expires_in_sec=3000)
    assert await c.link_health(USER) is LinkHealth.REVOKED


@pytest.mark.asyncio
async def test_a_transient_auth_failure_is_not_reported_as_revoked():
    from tools.ind_money_auth import MCPAuthError

    async def flaky() -> dict:
        raise MCPAuthError("network blip")

    c = IndMoneyConnector(
        transport=FixtureTransport(), clock=lambda: NOW, sleep=Sleeper(),
        auth_status=flaky,
    )
    assert await c.link_health(USER) is LinkHealth.NEEDS_RELINK


# --------------------------------------------------------------------------
# Nothing escapes the abstraction untyped (fix round 1)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_dead_credential_surfaces_as_not_linked():
    """The MCP client's own exception must never reach a caller. A caller
    writing `except PortfolioSourceError` has to catch everything."""
    from tools.ind_money_auth import MCPAuthInvalid

    c = connector(raising(MCPAuthInvalid("refresh rejected")))
    with pytest.raises(NotLinked) as excinfo:
        await c.fetch_snapshot(USER)
    assert isinstance(excinfo.value, PortfolioSourceError)
    # ... and a dead grant is remembered, not re-probed as if it might recover.
    assert await c.link_health(USER) is LinkHealth.REVOKED


@pytest.mark.asyncio
async def test_a_transport_failure_surfaces_as_source_unavailable():
    from tools.ind_money import MCPClientError

    c = connector(raising(MCPClientError("IND_MONEY_MCP_URL is not set")))
    with pytest.raises(SourceUnavailable) as excinfo:
        await c.fetch_holdings(USER, AssetType.MF)
    assert isinstance(excinfo.value, PortfolioSourceError)


@pytest.mark.asyncio
async def test_a_transient_auth_failure_is_source_unavailable_not_not_linked():
    from tools.ind_money_auth import MCPAuthError

    c = connector(raising(MCPAuthError("connection reset")))
    with pytest.raises(SourceUnavailable):
        await c.fetch_snapshot(USER)
    # Transient: the credential is not condemned on a network blip.
    assert await c.link_health(USER) is LinkHealth.LINKED


@pytest.mark.asyncio
async def test_an_arbitrary_transport_exception_is_still_typed():
    c = connector(raising(RuntimeError("something the client library did")))
    with pytest.raises(PortfolioSourceError):
        await c.fetch_sips(USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["1,234.56", "NaN", "Infinity", {}, []])
async def test_a_malformed_money_value_is_typed_and_says_where(bad):
    """A thousands separator or a NaN is a shape deviation, not a number.
    Neither may escape as a bare ValueError or as a pydantic ValidationError
    several frames later."""
    with pytest.raises(PayloadShapeError) as excinfo:
        await connector(one_shot(mf_rows(mf_row(market_value=bad)))).fetch_holdings(
            USER, AssetType.MF
        )
    assert "holdings[0].market_value" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_malformed_aggregate_value_is_typed_too():
    payload = copy.deepcopy(load("networth_snapshot.json"))
    payload["investments"][0]["current_value"] = "1,234.56"
    with pytest.raises(PayloadShapeError, match=r"investments\[0\]"):
        await connector(one_shot(payload)).fetch_snapshot(USER)


# --------------------------------------------------------------------------
# Failure must never be rendered as emptiness (fix round 1)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["holding_error", "position_error"])
async def test_a_broker_side_fetch_failure_is_not_an_empty_portfolio(flag):
    """The live-trading envelope reports a failed broker fetch in a flag while
    still returning `holdings: []`. Mapping that to [] tells the user they own
    nothing, which is a lie with a plausible face."""
    payload = copy.deepcopy(load("networth_holdings__IND_STOCK__empty.json"))
    payload[flag] = True
    with pytest.raises(SourceReportedError) as excinfo:
        await connector(one_shot(payload)).fetch_holdings(USER, AssetType.IND_STOCK)
    assert flag in str(excinfo.value)
    assert not isinstance(excinfo.value, RateLimited)


@pytest.mark.asyncio
async def test_the_flags_being_false_is_the_ordinary_empty_case():
    payload = load("networth_holdings__IND_STOCK__empty.json")
    assert payload["holding_error"] is False
    assert await connector(one_shot(payload)).fetch_holdings(USER, AssetType.IND_STOCK) == []


# --------------------------------------------------------------------------
# Identity must not silently merge two positions (fix round 1)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_id_fallback_does_not_merge_two_indistinguishable_rows():
    """Two rows with no instrument code, no name and no broker, but genuinely
    different holdings. Hashing only the descriptive fields gave them the SAME
    id — the exact silent merge the primary id is designed to avoid."""
    blank = dict(investment_code="", investment="", broker="")
    payload = mf_rows(
        mf_row(market_value=110000.0, invested_amount=100000.0, **blank),
        mf_row(market_value=250000.0, invested_amount=200000.0, **blank),
    )
    holdings = await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF)
    assert len(holdings) == 2
    assert holdings[0].external_id != holdings[1].external_id


@pytest.mark.asyncio
async def test_the_id_fallback_is_deterministic_for_the_same_response():
    blank = dict(investment_code="", investment="", broker="")
    payload = mf_rows(mf_row(**blank), mf_row(market_value=9.0, **blank))
    first = await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF)
    second = await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF)
    assert [h.external_id for h in first] == [h.external_id for h in second]


@pytest.mark.asyncio
async def test_a_coded_row_keeps_the_same_id_regardless_of_position():
    """The fallback's position-dependence must not infect coded rows, which are
    the overwhelming majority."""
    a = mf_row(investment_code="FIXT000111")
    b = mf_row(investment_code="FIXT000222")
    forward = await connector(one_shot(mf_rows(a, b))).fetch_holdings(USER, AssetType.MF)
    backward = await connector(one_shot(mf_rows(b, a))).fetch_holdings(USER, AssetType.MF)
    assert {h.external_id for h in forward} == {h.external_id for h in backward}


# --------------------------------------------------------------------------
# The vendor's own P&L wins where it exists (fix round 1)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_sources_own_pnl_is_passed_through_not_recomputed():
    """The source's figures may legitimately disagree with
    `current_value - invested_amount` (different refreshes, fees, rounding).
    Recomputing would quietly overwrite the source's answer with our own."""
    payload = mf_rows(mf_row(
        invested_amount=100000.0, market_value=110000.0,
        total_pnl=7777.0, pnl_per=7.77,   # deliberately NOT 10000.0 / 10.0
    ))
    holding = (await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF))[0]
    assert holding.pnl == Decimal("7777.0")
    assert holding.pnl_pct == Decimal("7.77")
    assert holding.current_value - holding.invested_amount == Decimal("10000.0")


@pytest.mark.asyncio
async def test_a_partial_source_pnl_falls_back_to_deriving_both():
    """One figure without the other is not a usable pass-through."""
    payload = mf_rows(mf_row(
        invested_amount=100000.0, market_value=110000.0, total_pnl=7777.0,
    ))
    payload["holdings"][0].pop("pnl_per")
    holding = (await connector(one_shot(payload)).fetch_holdings(USER, AssetType.MF))[0]
    assert holding.pnl == Decimal("10000.0")
    assert holding.pnl_pct == Decimal("10.00")


# --------------------------------------------------------------------------
# Aggregate slices degrade the same way rows do (fix round 1)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_zero_invested_bucket_degrades_instead_of_raising():
    """0 means unknown at the aggregate level too. Without that mapping the
    model's own guard fires and the caller gets a bare ValidationError."""
    payload = copy.deepcopy(load("networth_snapshot.json"))
    payload["investments"][0]["invested_value"] = 0
    snapshot = await connector(one_shot(payload)).fetch_snapshot(USER)
    bucket = snapshot.by_asset_type[0]
    assert bucket.invested_amount is None
    assert bucket.pnl is None and bucket.pnl_pct is None
    assert bucket.current_value > 0  # the value itself is still known


@pytest.mark.asyncio
async def test_a_zero_invested_breakdown_slice_degrades_too():
    payload = copy.deepcopy(load("networth_allocation_breakdown__MF__assets.json"))
    payload["data"][0]["invested_value"] = 0
    allocation = await connector(one_shot(payload)).fetch_allocation(
        USER, AssetType.MF, BreakdownBy.ASSETS
    )
    assert allocation.slices[0].invested_amount is None
    assert allocation.slices[0].pnl is None


# --------------------------------------------------------------------------
# Throttling details (fix round 1)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_throttle_without_a_delay_still_waits():
    """The global-tier envelope is UNVERIFIED, so an absent `retry_after_seconds`
    is plausible — and retrying instantly only deepens the breach."""
    body = dict(load("rate_limit_error__tool_scope.json"))
    body.pop("retry_after_seconds")
    transport = FixtureTransport(queue=[body])
    sleeper = Sleeper()
    c = IndMoneyConnector(
        transport=transport, clock=lambda: NOW, sleep=sleeper,
        auth_status=_status(authenticated=True, expires_in_sec=3000),
    )
    await c.fetch_holdings(USER, AssetType.MF)
    assert sleeper.waits and sleeper.waits[0] >= 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [False, "", 0, None])
async def test_a_falsy_error_key_is_not_an_error(value):
    """`error: false` is a field, not a failure. Treating any present `error`
    key as a breach would reject perfectly ordinary payloads."""
    payload = dict(load("networth_snapshot.json"), error=value)
    snapshot = await connector(one_shot(payload)).fetch_snapshot(USER)
    assert snapshot.net_worth > 0


# --------------------------------------------------------------------------
# Strictness behind the UNVERIFIED boundary (fix round 1)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_strict_mode_requires_the_whole_documented_key_set():
    """"Matches the documented shape" means the whole 14-key row, not just the
    one field the mapper happens to read."""
    payload = copy.deepcopy(load("networth_holdings__IND_STOCK__populated.UNVERIFIED.json"))
    payload["holdings"][0].pop("holding_percent")
    with pytest.raises(UnverifiedShapeError, match="holding_percent"):
        await connector(one_shot(payload)).fetch_holdings(USER, AssetType.IND_STOCK)


@pytest.mark.asyncio
async def test_strict_mode_still_tolerates_the_legitimately_absent_cost_basis():
    payload = copy.deepcopy(load("networth_holdings__IND_STOCK__populated.UNVERIFIED.json"))
    payload["holdings"][0].pop("invested_amount")
    holdings = await connector(one_shot(payload)).fetch_holdings(USER, AssetType.IND_STOCK)
    assert holdings[0].invested_amount is None
    assert holdings[0].pnl is None


# --------------------------------------------------------------------------
# The reconciliation gap, as THIS source's fixtures exhibit it
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_holdings_sum_does_not_equal_the_snapshot_total():
    """A property of this source's data, not of the interface: an un-enumerable
    bucket plus per-type residuals mean no equality holds. Pinned here so
    nobody can add a reconciliation check without a test going red."""
    c = connector()
    rows = []
    for asset_type in AssetType.queryable():
        rows.extend(await c.fetch_holdings(USER, asset_type))
    snapshot = await connector().fetch_snapshot(USER)
    assert rows
    assert sum_holdings_value(rows) != snapshot.gross_value
    assert sum_holdings_value(rows) != snapshot.net_worth
