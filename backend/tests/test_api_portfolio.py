"""API tests for the D1 portfolio routes.

Three things are pinned here, and each one is a way this surface could go wrong
without anybody noticing:

1. **The exposure gate.** These routes serve real holdings under a per-user
   identity; a regression that drops the auth check publishes one person's net
   worth. As of card L1 the gate is JWT-only in production (the interim C0 admin
   path was removed): an anonymous request 401s, an **admin header no longer
   authenticates anything**, and only single-tenant dev
   (``ALPHADESK_SINGLE_TENANT=1``) serves ``"local"`` without a token.
2. **The typed-error mapping.** Every ``PortfolioSourceError`` must arrive as a
   status the frontend can act on, with a stable machine-readable ``code`` —
   never a raw 500, and never the source's own message text.
3. **The response shapes**, against the stub connector's invented portfolio, so
   the null-cost-basis and no-reconciliation rules survive serialization.

The shape/error tests run in single-tenant mode so a headerless request
authenticates as ``"local"``; they inject the connector through FastAPI's
dependency override, so no network is touched.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.portfolio import connector_for_request
from portfolio.connectors import PortfolioConnector, StubConnector
from portfolio.errors import (
    NonInrValue,
    NotLinked,
    PayloadShapeError,
    PortfolioSourceError,
    RateLimited,
    SourceUnavailable,
    UnsupportedAssetType,
    UnverifiedShapeError,
    UserScopeError,
)
from portfolio.models import AssetType, BreakdownBy, LinkHealth

#: A stale admin header — it must authenticate nothing after L1.
ADMIN = {"x-alphadesk-admin-secret": "test-admin-secret"}

#: Every gated route, with the query string it needs to get past validation.
ROUTES = (
    "/portfolio/summary",
    "/portfolio/holdings?asset_type=MF",
    "/portfolio/allocation?asset_type=MF&by=sector",
    "/portfolio/history",
    # Card B10. The write methods are gated by the same dependency and are
    # covered in `test_api_manual_fd.py`, which can send them a body.
    "/portfolio/fds",
)


@pytest.fixture(autouse=True)
def local_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-tenant dev by default, so a headerless request is ``"local"``.

    The shape and error-mapping tests are about serialization and status codes,
    not identity, so they run as the local operator. The gate tests below flip
    ``ALPHADESK_SINGLE_TENANT`` off explicitly to exercise the 401 path. A stale
    ``ALPHADESK_ADMIN_SECRET`` is set to prove it is inert now.
    """
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")
    monkeypatch.setenv("ALPHADESK_ADMIN_SECRET", "test-admin-secret")


@pytest.fixture(autouse=True)
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """This module tests the D1 surface **without** a database.

    `api.main` calls `load_dotenv()`, so a developer's `backend/.env` puts a real
    `DATABASE_URL` into the environment — and these assertions would then depend
    on whatever rows happen to be in that developer's local Postgres. (That is
    not hypothetical: `test_summary_shape` started failing the moment an
    end-to-end run left snapshots in the dev database.)

    Clearing it also stops these tests from firing S1's opportunistic background
    capture at a database nobody asked them to write to. Snapshot behaviour
    against a real database lives in `test_snapshots_api.py`, which points the
    session dependency at the throwaway test DB on purpose.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)


class _RaisingConnector(PortfolioConnector):
    """A connector that fails the same way on every call.

    Deliberately not a mock library: the point is to prove the *interface's*
    error contract survives the route layer, so it implements the interface.
    """

    source = "raising"

    def __init__(self, error: PortfolioSourceError) -> None:
        self._error = error

    async def fetch_snapshot(self, user_id: str) -> Any:
        raise self._error

    async def fetch_holdings(self, user_id: str, asset_type: AssetType) -> Any:
        raise self._error

    async def fetch_allocation(self, user_id: str, asset_type: AssetType, by: BreakdownBy) -> Any:
        raise self._error

    async def fetch_sips(self, user_id: str) -> Any:
        raise self._error

    async def link_health(self, user_id: str) -> LinkHealth:
        raise self._error


def _client(connector: PortfolioConnector) -> Iterator[TestClient]:
    app.dependency_overrides[connector_for_request] = lambda: connector
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(connector_for_request, None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from _client(StubConnector())


# --------------------------------------------------------------------------- #
# The exposure gate (JWT-only in production as of L1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("route", ROUTES)
def test_gate_rejects_anonymous(
    client: TestClient, route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With single-tenant off and no token, `/portfolio/*` is 401."""
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    assert client.get(route).status_code == 401


@pytest.mark.parametrize("route", ROUTES)
def test_admin_header_no_longer_authenticates(
    client: TestClient, route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The F3 §5 removal, pinned: the interim admin secret is inert now.

    Presenting it — even with `ALPHADESK_ADMIN_SECRET` set — authenticates
    nothing; the route answers 401 exactly as it would to an anonymous caller.
    """
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    assert client.get(route, headers=ADMIN).status_code == 401


@pytest.mark.parametrize("route", ROUTES)
def test_single_tenant_dev_serves_local_without_a_token(
    client: TestClient, route: str
) -> None:
    """Local-dev only — ``ALPHADESK_SINGLE_TENANT=1`` (set by the autouse
    fixture) is the operator's own machine, so a headerless request is served as
    ``"local"``. It must stay unset in every deployed environment."""
    assert client.get(route).status_code == 200


# --------------------------------------------------------------------------- #
# Typed source failures -> HTTP
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (NotLinked("no credential"), 409, "not_linked"),
        (UnsupportedAssetType("no such bucket"), 400, "unsupported_asset_type"),
        (UserScopeError("wrong user"), 403, "user_scope"),
        (UnverifiedShapeError("never observed"), 502, "unverified_shape"),
        (NonInrValue("tool", "data[0].currency", "USD"), 502, "non_inr"),
        (PayloadShapeError("missing key"), 502, "payload_shape"),
        (SourceUnavailable("transport died"), 502, "source_unavailable"),
    ],
)
def test_error_mapping(error: PortfolioSourceError, status: int, code: str) -> None:
    for client in _client(_RaisingConnector(error)):
        response = client.get("/portfolio/holdings?asset_type=MF")
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code


def test_rate_limited_carries_retry_after() -> None:
    error = RateLimited("tool", "throttled", retry_after=12.0, scope="per_tool", limit=15)
    for client in _client(_RaisingConnector(error)):
        response = client.get("/portfolio/summary")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "12"
        detail = response.json()["detail"]
        assert detail["code"] == "rate_limited"
        assert detail["retry_after"] == 12.0
        assert detail["scope"] == "per_tool"


def test_not_linked_carries_a_connect_hint() -> None:
    for client in _client(_RaisingConnector(NotLinked("no credential"))):
        detail = client.get("/portfolio/summary").json()["detail"]
        assert detail["connect"] == {"method": "POST", "path": "/auth/login"}


def test_source_message_text_never_reaches_the_client() -> None:
    """Fixed messages, not the exception's — a source's error body can quote
    payload fragments, and this response is public to every caller past the
    gate."""
    for client in _client(_RaisingConnector(SourceUnavailable("token abc123 rejected by host"))):
        body = client.get("/portfolio/summary").text
        assert "abc123" not in body


# --------------------------------------------------------------------------- #
# Response shapes (stub connector — invented portfolio)
# --------------------------------------------------------------------------- #
def test_summary_shape(client: TestClient) -> None:
    body = client.get("/portfolio/summary").json()

    assert body["user_id"] == "local"
    assert body["source"] == "stub"
    assert body["currency"] == "INR"
    assert body["link_health"] == LinkHealth.LINKED.value
    # No database configured here (see the `no_database` fixture), so there is
    # honestly nothing captured — and a fabricated timestamp would be a lie.
    assert body["last_captured_at"] is None
    # Money is a string, never a JSON number.
    for key in ("net_worth", "current_value", "invested_total", "pnl", "pnl_pct"):
        assert isinstance(body[key], str), key
    # 1152655 - 1063750 on the invented fixture. The string keeps the source's
    # own precision verbatim — a float round-trip is exactly what it must not do.
    assert body["pnl"] == "88905.0"
    assert body["pnl_pct"] == "8.36"
    # All four breakdowns ride the one snapshot call.
    assert [s["asset_type"] for s in body["by_asset_type"]].count("MF") == 1
    assert body["by_sector"] and body["by_market_cap"] and body["by_asset_class"]
    # The out-of-enum bucket survives as UNKNOWN with its original string, and
    # is flagged as US exposure so the dashboard can badge it.
    wallet = next(s for s in body["by_asset_type"] if s["asset_type_raw"] == "US_STOCK_WALLET")
    assert wallet["asset_type"] == "UNKNOWN"
    assert wallet["us_exposure"] is True


def test_holdings_shape_and_null_cost_basis(client: TestClient) -> None:
    body = client.get("/portfolio/holdings?asset_type=MF").json()
    rows = {row["external_id"]: row for row in body["holdings"]}

    assert body["asset_type"] == "MF"
    # Unknown cost basis: null all the way through, never a fabricated return.
    unknown = rows["DEMO-MF-0002"]
    assert unknown["invested_amount"] is None
    assert unknown["pnl"] is None and unknown["pnl_pct"] is None
    # A real wipe-out with a known basis keeps its honest -100%.
    wiped = rows["DEMO-MF-0003"]
    assert wiped["invested_amount"] == "12000.0"
    assert wiped["pnl_pct"] == "-100.00"
    # `raw` is never serialized — vendor rows stay below the boundary.
    assert "raw" not in unknown


def test_holdings_empty_bucket_is_not_an_error(client: TestClient) -> None:
    body = client.get("/portfolio/holdings?asset_type=NPS").json()
    assert body["holdings"] == []


def test_holdings_rejects_an_unknown_asset_type(client: TestClient) -> None:
    response = client.get("/portfolio/holdings?asset_type=BULLION")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unknown_asset_type"


def test_allocation_shape(client: TestClient) -> None:
    body = client.get("/portfolio/allocation?asset_type=MF&by=sector").json()
    assert body["asset_type"] == "MF"
    assert body["by"] == "sector"
    labels = [s["label"] for s in body["slices"]]
    assert "Demo Sector Delta" in labels
    assert all(isinstance(s["weight_pct"], str) for s in body["slices"])


def test_allocation_rejects_an_unknown_breakdown(client: TestClient) -> None:
    response = client.get("/portfolio/allocation?asset_type=MF&by=vibes")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unknown_breakdown"


def test_history_is_honestly_empty_without_a_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Postgres configured → an empty series and a note, never a 500.

    The live figures on this dashboard come from the source, not the database.
    A deployment that has not been wired to Postgres yet still renders; it just
    has no past to draw. S1 must not have turned an additive feature into a
    hard dependency — `backend/tests/test_snapshots_api.py` covers the case
    where the database *is* there.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = client.get("/portfolio/history?days=30")
    assert response.status_code == 200
    body = response.json()
    assert body["points"] == []
    assert body["last_captured_at"] is None
    assert body["days"] == 30
    assert "no history" in body["note"].lower()


def test_summary_survives_a_missing_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`last_captured_at` degrades to null; nothing else about /summary moves."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = client.get("/portfolio/summary")
    assert response.status_code == 200
    assert response.json()["last_captured_at"] is None
