"""`/portfolio/fds` over HTTP against the real app and the real Postgres (B10).

Card B10 puts the first *user-authored* rows into the schema, so the claims
pinned here are ownership, durability and additivity:

1. **CRUD round-trips, and an edit moves the valuation.** The stored terms are
   the only state; every computed field is recomputed on read.
2. **A caller sees and edits only their own.** Another user's id is a **404**,
   never a 403 — the F4 rule, applied to a new resource.
3. **A deposit is durable data or an error.** With no `DATABASE_URL` reads
   degrade to an empty list with a note, and writes answer **503
   `no_database`** rather than landing in a process dict that dies on restart.
4. **The merge is additive.** `/portfolio/holdings?asset_type=FD` gains the
   manual rows after the read-through cache (so a write shows up immediately and
   nothing manual is ever cached), `/portfolio/summary` gains a `manual` block,
   and every vendor-derived figure is byte-identical.
5. **It cascades.** Deleting the user leaves zero `manual_fds` rows, with no
   code in the delete path.

The vendor side is the `StubConnector` (a real second connector, no network);
the database is the throwaway Postgres from `docs/TESTING/F1.md`.

**Fixed deposits that have already matured are used wherever an exact figure is
asserted.** Their value is frozen by the terms, so the expected numbers stay
right forever instead of drifting with the date the suite happens to run on.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from api import main
from api.routes import portfolio as portfolio_routes
from api.routes.portfolio import connector_for_request
from db.models import ManualFd, User
from portfolio.connectors import StubConnector
from services import adoption
from tests.clerk_stub import bearer, clerk, clerk_key  # noqa: F401
from tools import ind_money_auth as auth

USER_A = "user_2ffffffffffffffffffffffffd"
USER_B = "user_2ffffffffffffffffffffffffe"

#: A deposit that matured on 2026-01-01: 100000 at 8% compounded quarterly for
#: exactly 365 days. 100000 x 1.02^4 = 108243.216 -> 108243.22, and it stays
#: 108243.22 forever because accrual freezes at maturity.
MATURED_FD = {
    "label": "HDFC Bank FD",
    "principal": "100000",
    "rate_pct": "8",
    "compounding": "quarterly",
    "start_date": "2025-01-01",
    "maturity_date": "2026-01-01",
}
MATURED_VALUE = "108243.22"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ALPHADESK_SINGLE_TENANT", raising=False)
    monkeypatch.delenv(adoption.OPERATOR_EMAIL_ENV, raising=False)
    auth.reset_auth_stores()
    adoption.reset_adoption_cache()
    portfolio_routes.reset_connector()
    yield
    auth.reset_auth_stores()
    adoption.reset_adoption_cache()
    portfolio_routes.reset_connector()
    main.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_opportunistic_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """S1's third net is not this card's business.

    `/portfolio/summary` fires a background capture when today has no snapshot
    row. Left alone it would write snapshot rows mid-test and move
    `last_captured_at` between two reads that are supposed to be comparable.
    """
    monkeypatch.setattr(portfolio_routes, "schedule_capture_if_missing", lambda *a, **k: None)


@pytest.fixture
async def client(db_env: Any) -> Any:
    """The app over ASGI, with the demo connector standing in for the source."""
    main.app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://testserver"
    ) as http:
        yield http


@pytest.fixture
async def no_db_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The app with **no** database configured at all — the 503 write path."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://testserver"
    ) as http:
        yield http


async def _create(client: Any, key: rsa.RSAPrivateKey, user: str, **overrides: Any) -> dict:
    body = {**MATURED_FD, **overrides}
    response = await client.post("/portfolio/fds", json=body, headers=bearer(key, user))
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# 1. CRUD round-trip
# --------------------------------------------------------------------------- #
async def test_create_returns_201_and_the_full_row_shape(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    row = await _create(client, clerk, USER_A)

    assert set(row) == {
        "id",
        "label",
        "principal",
        "rate_pct",
        "compounding",
        "start_date",
        "maturity_date",
        "current_value",
        "accrued_interest",
        "maturity_value",
        "matured",
        "days_to_maturity",
        "created_at",
        "updated_at",
    }
    assert row["label"] == "HDFC Bank FD"
    # Money is a string, never a JSON number — the `_num` convention.
    assert row["principal"] == "100000.00"
    assert row["rate_pct"] == "8.0000"
    assert row["current_value"] == MATURED_VALUE
    assert row["accrued_interest"] == "8243.22"
    assert row["maturity_value"] == MATURED_VALUE
    assert row["matured"] is True
    assert row["days_to_maturity"] == 0
    assert row["id"] and len(row["id"]) == 32


async def test_list_returns_what_was_created_and_a_null_note(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    created = await _create(client, clerk, USER_A)

    body = (await client.get("/portfolio/fds", headers=bearer(clerk, USER_A))).json()
    assert body["note"] is None
    assert [f["id"] for f in body["fds"]] == [created["id"]]
    assert body["fds"][0]["current_value"] == MATURED_VALUE


async def test_list_is_ordered_by_soonest_maturity(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    late = await _create(client, clerk, USER_A, label="Later", maturity_date="2027-01-01")
    early = await _create(client, clerk, USER_A, label="Sooner")

    body = (await client.get("/portfolio/fds", headers=bearer(clerk, USER_A))).json()
    assert [f["id"] for f in body["fds"]] == [early["id"], late["id"]]


async def test_default_compounding_is_quarterly(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """Indian bank FDs compound quarterly; the body may omit the field."""
    body = {k: v for k, v in MATURED_FD.items() if k != "compounding"}
    response = await client.post(
        "/portfolio/fds", json=body, headers=bearer(clerk, USER_A)
    )
    assert response.status_code == 201, response.text
    assert response.json()["compounding"] == "quarterly"


async def test_editing_the_rate_moves_the_accrual(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """The whole point of storing terms rather than a value.

    Same matured deposit at 10%: 100000 x 1.025^4 = 110381.2890625 -> 110381.29.
    """
    row = await _create(client, clerk, USER_A)
    assert row["current_value"] == MATURED_VALUE

    response = await client.patch(
        f"/portfolio/fds/{row['id']}",
        json={"rate_pct": "10"},
        headers=bearer(clerk, USER_A),
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["rate_pct"] == "10.0000"
    assert edited["current_value"] == "110381.29"
    assert edited["maturity_value"] == "110381.29"
    # Untouched fields survive a partial edit.
    assert edited["label"] == row["label"]
    assert edited["principal"] == row["principal"]
    # And the list agrees with the row the write returned.
    listed = (await client.get("/portfolio/fds", headers=bearer(clerk, USER_A))).json()
    assert listed["fds"][0]["current_value"] == "110381.29"


async def test_editing_the_principal_moves_the_accrual(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """200000 x 1.02^4 = 216486.432 -> 216486.43."""
    row = await _create(client, clerk, USER_A)
    response = await client.patch(
        f"/portfolio/fds/{row['id']}",
        json={"principal": "200000"},
        headers=bearer(clerk, USER_A),
    )
    assert response.json()["current_value"] == "216486.43"


async def test_an_empty_patch_body_changes_nothing(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    row = await _create(client, clerk, USER_A)
    response = await client.patch(
        f"/portfolio/fds/{row['id']}", json={}, headers=bearer(clerk, USER_A)
    )
    assert response.status_code == 200
    unchanged = response.json()
    assert {k: v for k, v in unchanged.items() if k != "updated_at"} == {
        k: v for k, v in row.items() if k != "updated_at"
    }


async def test_delete_removes_the_row(client: Any, clerk: rsa.RSAPrivateKey) -> None:
    row = await _create(client, clerk, USER_A)

    response = await client.delete(
        f"/portfolio/fds/{row['id']}", headers=bearer(clerk, USER_A)
    )
    assert response.status_code == 204
    assert response.content == b""

    body = (await client.get("/portfolio/fds", headers=bearer(clerk, USER_A))).json()
    assert body["fds"] == []
    # And deleting it again is a 404, not a silent success.
    again = await client.delete(
        f"/portfolio/fds/{row['id']}", headers=bearer(clerk, USER_A)
    )
    assert again.status_code == 404


async def test_a_running_deposit_reports_a_live_accrual(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """A deposit still inside its term: not matured, worth more than principal
    and less than its maturity value, with a positive countdown."""
    future = date.today().replace(year=date.today().year + 3).isoformat()
    row = await _create(
        client, clerk, USER_A, start_date="2025-01-01", maturity_date=future
    )
    assert row["matured"] is False
    assert row["days_to_maturity"] > 0
    assert (
        float(row["principal"])
        < float(row["current_value"])
        < float(row["maturity_value"])
    )


# --------------------------------------------------------------------------- #
# 2. Ownership — 404, never 403
# --------------------------------------------------------------------------- #
async def test_another_users_deposit_is_invisible_in_the_list(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    await _create(client, clerk, USER_A)
    body = (await client.get("/portfolio/fds", headers=bearer(clerk, USER_B))).json()
    assert body["fds"] == []


async def test_patching_another_users_deposit_is_404_not_403(
    client: Any, clerk: rsa.RSAPrivateKey, db_env: Any
) -> None:
    row = await _create(client, clerk, USER_A)

    response = await client.patch(
        f"/portfolio/fds/{row['id']}",
        json={"label": "stolen"},
        headers=bearer(clerk, USER_B),
    )
    assert response.status_code == 404  # existence is not leaked

    # And the row is untouched — the check fired before any write.
    async with db_env() as session:
        stored = (
            await session.execute(select(ManualFd).where(ManualFd.id == row["id"]))
        ).scalars().one()
        assert stored.label == "HDFC Bank FD"


async def test_deleting_another_users_deposit_is_404_and_leaves_it_alone(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    row = await _create(client, clerk, USER_A)

    response = await client.delete(
        f"/portfolio/fds/{row['id']}", headers=bearer(clerk, USER_B)
    )
    assert response.status_code == 404

    owner = (await client.get("/portfolio/fds", headers=bearer(clerk, USER_A))).json()
    assert [f["id"] for f in owner["fds"]] == [row["id"]]


async def test_an_id_that_never_existed_is_also_404(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """The same status as another user's id — that is what makes it safe."""
    response = await client.patch(
        "/portfolio/fds/deadbeefdeadbeefdeadbeefdeadbeef",
        json={"label": "x"},
        headers=bearer(clerk, USER_A),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# 3. The identity gate
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/portfolio/fds", None),
        ("POST", "/portfolio/fds", MATURED_FD),
        ("PATCH", "/portfolio/fds/abc", {"label": "x"}),
        ("DELETE", "/portfolio/fds/abc", None),
    ],
)
async def test_every_method_requires_an_identity(
    client: Any, method: str, path: str, body: Any
) -> None:
    """Single-tenant off and no token: 401 on all four, never a fall-through."""
    response = await client.request(method, path, json=body)
    assert response.status_code == 401


async def test_single_tenant_dev_creates_the_local_users_row_for_the_fk(
    client: Any, db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`"local"` has no Clerk token and therefore no `register_identity` — the
    write path has to insert the parent row itself or the FK fails on the very
    first deposit the operator enters."""
    monkeypatch.setenv("ALPHADESK_SINGLE_TENANT", "1")

    response = await client.post("/portfolio/fds", json=MATURED_FD)
    assert response.status_code == 201, response.text

    async with db_env() as session:
        assert (
            await session.execute(select(User).where(User.id == "local"))
        ).scalars().first() is not None
        stored = (await session.execute(select(ManualFd))).scalars().all()
        assert [fd.user_id for fd in stored] == ["local"]


# --------------------------------------------------------------------------- #
# 4. Validation — 422 on anything that would store a nonsense deposit
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"principal": "0"}, id="zero-principal"),
        pytest.param({"principal": "-5000"}, id="negative-principal"),
        pytest.param({"rate_pct": "0"}, id="zero-rate"),
        pytest.param({"rate_pct": "725"}, id="rate-typo-above-50"),
        pytest.param({"compounding": "fortnightly"}, id="unknown-compounding"),
        pytest.param({"label": "   "}, id="blank-label"),
        pytest.param({"label": "x" * 121}, id="label-too-long"),
        pytest.param(
            {"start_date": "2026-01-01", "maturity_date": "2025-01-01"}, id="inverted-term"
        ),
        pytest.param(
            {"start_date": "2026-01-01", "maturity_date": "2026-01-01"}, id="zero-length-term"
        ),
        pytest.param({"principal": "not-a-number"}, id="non-numeric-principal"),
        pytest.param({"maturity_date": "not-a-date"}, id="non-date"),
        pytest.param({"nickname": "extra"}, id="unknown-field"),
    ],
)
async def test_create_rejects_a_nonsense_deposit(
    client: Any, clerk: rsa.RSAPrivateKey, overrides: dict
) -> None:
    response = await client.post(
        "/portfolio/fds",
        json={**MATURED_FD, **overrides},
        headers=bearer(clerk, USER_A),
    )
    assert response.status_code == 422, response.text


async def test_a_missing_required_field_is_422(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    response = await client.post(
        "/portfolio/fds", json={"label": "only a label"}, headers=bearer(clerk, USER_A)
    )
    assert response.status_code == 422


async def test_patch_cannot_invert_the_term_against_the_stored_row(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """The check the body alone cannot make: moving only `maturity_date` back
    before the *stored* `start_date` still has to be refused."""
    row = await _create(client, clerk, USER_A)

    response = await client.patch(
        f"/portfolio/fds/{row['id']}",
        json={"maturity_date": "2024-06-01"},
        headers=bearer(clerk, USER_A),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_terms"

    # Nothing was written.
    listed = (await client.get("/portfolio/fds", headers=bearer(clerk, USER_A))).json()
    assert listed["fds"][0]["maturity_date"] == "2026-01-01"


async def test_patch_rejects_a_bad_value_the_same_way_create_does(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    row = await _create(client, clerk, USER_A)
    for bad in ({"principal": "0"}, {"rate_pct": "99"}, {"compounding": "weekly"}):
        response = await client.patch(
            f"/portfolio/fds/{row['id']}", json=bad, headers=bearer(clerk, USER_A)
        )
        assert response.status_code == 422, bad


# --------------------------------------------------------------------------- #
# 5. No database — read degrades, write refuses
# --------------------------------------------------------------------------- #
async def test_list_without_a_database_is_200_with_a_note(
    no_db_client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    response = await no_db_client.get("/portfolio/fds", headers=bearer(clerk, USER_A))
    assert response.status_code == 200
    body = response.json()
    assert body["fds"] == []
    assert "database" in (body["note"] or "").lower()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/portfolio/fds", MATURED_FD),
        ("PATCH", "/portfolio/fds/abc", {"label": "x"}),
        ("DELETE", "/portfolio/fds/abc", None),
    ],
)
async def test_writes_without_a_database_are_503_not_a_silent_memory_write(
    no_db_client: Any,
    clerk: rsa.RSAPrivateKey,
    method: str,
    path: str,
    body: Any,
) -> None:
    """The deliberate difference from the watchlist's in-memory fallback: a
    financial record the user typed in is durable or it is an error."""
    response = await no_db_client.request(
        method, path, json=body, headers=bearer(clerk, USER_A)
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "no_database"


# --------------------------------------------------------------------------- #
# 6. The additive merge into the dashboard
# --------------------------------------------------------------------------- #
async def _fd_holdings(client: Any, key: rsa.RSAPrivateKey, user: str) -> dict:
    response = await client.get(
        "/portfolio/holdings?asset_type=FD", headers=bearer(key, user)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_holdings_fd_carries_manual_rows_alongside_vendor_rows(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    before = await _fd_holdings(client, clerk, USER_A)
    vendor = [h for h in before["holdings"] if h["source"] != "manual"]
    assert vendor, "the demo portfolio is supposed to contain a vendor FD"

    row = await _create(client, clerk, USER_A)
    after = await _fd_holdings(client, clerk, USER_A)

    manual = [h for h in after["holdings"] if h["source"] == "manual"]
    assert len(manual) == 1
    entry = manual[0]
    assert entry["external_id"] == row["id"]
    assert entry["asset_type"] == "FD"
    assert entry["name"] == "HDFC Bank FD"
    assert entry["invested_amount"] == "100000.00"
    assert entry["current_value"] == MATURED_VALUE
    assert entry["pnl"] == "8243.22"
    # Every vendor row is exactly as it was.
    assert [h for h in after["holdings"] if h["source"] != "manual"] == vendor


async def test_a_new_deposit_appears_immediately_despite_the_holdings_cache(
    client: Any, clerk: rsa.RSAPrivateKey, db_env: Any
) -> None:
    """The reason manual rows are merged *after* the cache: no invalidation.

    The first read populates the 15-minute `holdings:FD` cache entry. A deposit
    created a moment later must still show up on the very next read — and must
    not have been written into that cache entry.
    """
    await _fd_holdings(client, clerk, USER_A)  # warms the cache
    await _create(client, clerk, USER_A)
    await _create(client, clerk, USER_A, label="Second FD")

    after = await _fd_holdings(client, clerk, USER_A)
    assert len([h for h in after["holdings"] if h["source"] == "manual"]) == 2

    # The cached vendor payload never learned about them.
    async with db_env() as session:
        from db.models import PortfolioCache

        cached = (
            await session.execute(
                select(PortfolioCache).where(
                    PortfolioCache.user_id == USER_A,
                    PortfolioCache.cache_key == "holdings:FD",
                )
            )
        ).scalars().one()
    assert all(h["source"] != "manual" for h in cached.payload["holdings"])


async def test_other_asset_types_are_byte_identical(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """A manual FD changes the FD bucket and nothing else."""

    async def _mf() -> dict:
        body = (
            await client.get(
                "/portfolio/holdings?asset_type=MF&fresh=1",
                headers=bearer(clerk, USER_A),
            )
        ).json()
        # `as_of` is the connector's fetch time (M1 rule 3: no date comes from a
        # payload), so it legitimately differs between two forced re-reads.
        for row in body["holdings"]:
            row.pop("as_of")
        return body

    before = await _mf()
    await _create(client, clerk, USER_A)
    assert await _mf() == before


async def test_summary_gains_the_manual_block_and_changes_nothing_else(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    before = (
        await client.get("/portfolio/summary?fresh=1", headers=bearer(clerk, USER_A))
    ).json()
    assert before["manual"] == {"total": "0", "fd_count": 0}

    await _create(client, clerk, USER_A)
    await _create(client, clerk, USER_A, label="Second FD")

    after = (
        await client.get("/portfolio/summary?fresh=1", headers=bearer(clerk, USER_A))
    ).json()
    # 2 x 108243.22
    assert after["manual"] == {"total": "216486.44", "fd_count": 2}
    # Every vendor-derived field passes through untouched — this module never
    # recomputes the source's arithmetic, and the addition is the frontend's to
    # label. (`as_of` is the connector's own fetch stamp and moves between two
    # forced re-reads by design; everything else must not.)
    ignored = {"manual", "as_of"}
    assert {k: v for k, v in after.items() if k not in ignored} == {
        k: v for k, v in before.items() if k not in ignored
    }


async def test_the_summary_manual_block_is_never_served_stale_from_the_cache(
    client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    """Computed per request, on the cache-hit path too."""
    await client.get("/portfolio/summary", headers=bearer(clerk, USER_A))  # warms it
    await _create(client, clerk, USER_A)

    cached = (
        await client.get("/portfolio/summary", headers=bearer(clerk, USER_A))
    ).json()
    assert cached["manual"] == {"total": MATURED_VALUE, "fd_count": 1}


async def test_the_summary_manual_block_is_zero_without_a_database(
    no_db_client: Any, clerk: rsa.RSAPrivateKey
) -> None:
    main.app.dependency_overrides[connector_for_request] = lambda: StubConnector()
    body = (
        await no_db_client.get("/portfolio/summary", headers=bearer(clerk, USER_A))
    ).json()
    assert body["manual"] == {"total": "0", "fd_count": 0}


# --------------------------------------------------------------------------- #
# 7. The cascade — no code in the delete path, and that is the claim
# --------------------------------------------------------------------------- #
async def test_deleting_the_user_leaves_zero_manual_fds(
    client: Any, clerk: rsa.RSAPrivateKey, db_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_revoke(user_id: str) -> dict:
        return {"revoked": False}

    monkeypatch.setattr("api.routes.account.revoke_only", _no_revoke)

    await _create(client, clerk, USER_A)
    await _create(client, clerk, USER_B, label="Someone else's FD")

    response = await client.request("DELETE", "/account", headers=bearer(clerk, USER_A))
    assert response.status_code == 200, response.text

    async with db_env() as session:
        remaining = (await session.execute(select(ManualFd))).scalars().all()
        mine = await session.execute(
            select(func.count()).select_from(ManualFd).where(ManualFd.user_id == USER_A)
        )
    assert int(mine.scalar_one()) == 0
    # The other user's deposit is untouched — a cascade, not a truncate.
    assert [fd.user_id for fd in remaining] == [USER_B]
