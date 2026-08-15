"""The Clerk `current_user` dependency (card F2), without a Clerk account.

No Clerk instance exists yet, and none is needed: a Clerk session token is an
ordinary RS256 JWT signed by a key whose public half is published as a JWKS
document. So this suite **mints its own RSA key pair in-process**, serves the
matching JWKS by monkeypatching `PyJWKClient.fetch_data`, and signs tokens with
the private half. Every code path except "did Clerk really issue this" is
therefore exercised for real — including the ones that matter most, which are
the rejections.

Two groups:

- **verification** (`verify_token`, the header parser) — pure crypto and claim
  checks, no database, so they run on a laptop with nothing installed;
- **the dependency** — driven over HTTP through an ASGI client against the real
  migrated Postgres, because "a `users` row appears exactly once" is a claim
  about a database, and only a database can be asked.

What is *not* covered here, because it needs real keys: that Clerk's live JWKS
endpoint is reachable at the configured URL, and that a token minted by the
Clerk frontend carries the claims we expect. See `docs/TESTING/F2.md` §4.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, AsyncIterator, Iterator

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWKClientConnectionError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api import deps
from db.models import User
from db.session import async_session

ISSUER = "https://tidy-mayfly-99.clerk.accounts.dev"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
KID = "ins_2fXaMpLeKeYiD"
USER_ID = "user_2fXaMpLeUsErId"
ORIGIN = "https://alphadesk.example"


# --------------------------------------------------------------------------- #
# A self-contained Clerk stand-in: one RSA key pair and its JWKS
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    """The key pair this suite pretends is a Clerk instance's."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def other_key() -> rsa.RSAPrivateKey:
    """A second, unrelated key pair — the attacker's."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(key: rsa.RSAPrivateKey, kid: str = KID) -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


def _sign(key: rsa.RSAPrivateKey, claims: dict[str, Any], kid: str = KID) -> str:
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


def _claims(**overrides: Any) -> dict[str, Any]:
    """A plausible Clerk session-token payload."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": USER_ID,
        "iat": now,
        "nbf": now - 5,
        "exp": now + 3600,
        "azp": ORIGIN,
        "sid": "sess_2fXaMpLeSeSsIoN",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


class _JwksServer:
    """Stands in for the Clerk JWKS endpoint, and counts how often it is hit."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.fetches = 0

    def fetch_data(self) -> dict[str, Any]:
        """Replaces `PyJWKClient.fetch_data`.

        Patched in **already bound to this object**, so `PyJWKClient` calling
        `self.fetch_data()` lands here with no arguments — the client instance
        is deliberately not passed along.
        """
        self.fetches += 1
        return self.document


@pytest.fixture
def jwks_server(
    signing_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> Iterator[_JwksServer]:
    """Serve our JWKS to `PyJWKClient` and configure the env Clerk would fill.

    Patching `fetch_data` rather than the whole client keeps `PyJWKClient`'s own
    caching in the picture — which is the thing the "networkless" claim is
    about, so it has to be the real one.
    """
    server = _JwksServer(_jwks(signing_key))
    monkeypatch.setattr(PyJWKClient, "fetch_data", server.fetch_data)
    monkeypatch.setenv(deps.JWKS_URL_ENV, JWKS_URL)
    monkeypatch.setenv(deps.ISSUER_ENV, ISSUER)
    # F3 made the allow-list mandatory, so the baseline fixture configures it.
    monkeypatch.setenv(deps.AUTHORIZED_PARTIES_ENV, ORIGIN)
    yield server


@pytest.fixture(autouse=True)
def clean_module_caches() -> Iterator[None]:
    """No process-global state leaks between tests in this file."""
    deps.reset_jwk_clients()
    deps.reset_seen_users()
    yield
    deps.reset_jwk_clients()
    deps.reset_seen_users()


# --------------------------------------------------------------------------- #
# Header parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "abc.def.ghi",  # no scheme
        "Basic dXNlcjpwdw==",  # wrong scheme
        "Bearer",  # scheme only
        "Bearer   ",  # scheme and whitespace
    ],
)
def test_unusable_authorization_headers_are_401(header: str | None) -> None:
    with pytest.raises(Exception) as excinfo:
        deps.bearer_token(header)
    assert excinfo.value.status_code == 401  # type: ignore[attr-defined]
    assert excinfo.value.headers["WWW-Authenticate"] == "Bearer"  # type: ignore[attr-defined]


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_bearer_scheme_is_case_insensitive(scheme: str) -> None:
    assert deps.bearer_token(f"{scheme} tok-123") == "tok-123"


# --------------------------------------------------------------------------- #
# Verification: the happy path
# --------------------------------------------------------------------------- #
def test_a_valid_token_yields_its_claims(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    claims = deps.verify_token(_sign(signing_key, _claims()))
    assert claims["sub"] == USER_ID
    assert claims["iss"] == ISSUER


def test_jwks_is_fetched_once_and_then_verification_is_networkless(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    """The property the whole design rests on: one fetch, then local maths."""
    for _ in range(5):
        assert deps.verify_token(_sign(signing_key, _claims()))["sub"] == USER_ID
    assert jwks_server.fetches == 1


# --------------------------------------------------------------------------- #
# Verification: every way a token can be wrong
# --------------------------------------------------------------------------- #
def _assert_401(callable_: Any, *args: Any) -> str:
    with pytest.raises(Exception) as excinfo:
        callable_(*args)
    assert excinfo.value.status_code == 401, excinfo.value  # type: ignore[attr-defined]
    return str(excinfo.value.detail)  # type: ignore[attr-defined]


def test_expired_token_is_401(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    now = int(time.time())
    token = _sign(signing_key, _claims(iat=now - 7200, nbf=now - 7200, exp=now - 60))
    assert "ExpiredSignatureError" in _assert_401(deps.verify_token, token)


def test_not_yet_valid_token_is_401(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    now = int(time.time())
    token = _sign(signing_key, _claims(nbf=now + 600, exp=now + 3600))
    assert "ImmatureSignatureError" in _assert_401(deps.verify_token, token)


def test_wrong_issuer_is_401(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    token = _sign(signing_key, _claims(iss="https://evil.clerk.accounts.dev"))
    assert "InvalidIssuerError" in _assert_401(deps.verify_token, token)


def test_missing_issuer_is_401(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    token = _sign(signing_key, _claims(iss=None))
    _assert_401(deps.verify_token, token)


def test_missing_sub_is_401(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    token = _sign(signing_key, _claims(sub=None))
    _assert_401(deps.verify_token, token)


def test_blank_sub_is_401(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    token = _sign(signing_key, _claims(sub="   "))
    assert "no subject" in _assert_401(deps.verify_token, token)


def test_token_signed_by_another_key_is_401(
    jwks_server: _JwksServer, other_key: rsa.RSAPrivateKey
) -> None:
    """Same `kid`, different private key — the signature must not verify."""
    token = _sign(other_key, _claims())
    assert "InvalidSignatureError" in _assert_401(deps.verify_token, token)


def test_unknown_kid_is_401(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    token = _sign(signing_key, _claims(), kid="ins_notInTheJwks")
    assert "signing key" in _assert_401(deps.verify_token, token)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_alg_none_is_401(jwks_server: _JwksServer) -> None:
    """The classic: a token that asks to be trusted without a signature.

    Hand-assembled rather than produced by `jwt.encode`, because refusing to
    *emit* one is the library's own policy and says nothing about whether we
    would *accept* one.
    """
    header = _b64(json.dumps({"alg": "none", "typ": "JWT", "kid": KID}).encode())
    payload = _b64(json.dumps(_claims()).encode())
    assert _assert_401(deps.verify_token, f"{header}.{payload}.")


def test_hs256_signed_with_the_public_key_is_401(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    """Algorithm confusion: the public key is public, so it must never be a secret."""
    public_pem = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    payload = _b64(json.dumps(_claims()).encode())
    signature = _b64(
        hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    assert _assert_401(deps.verify_token, f"{header}.{payload}.{signature}")


def test_garbage_is_401(jwks_server: _JwksServer) -> None:
    assert _assert_401(deps.verify_token, "not-a-jwt-at-all")


# --------------------------------------------------------------------------- #
# Authorized parties (azp) — MANDATORY as of F3
# --------------------------------------------------------------------------- #
def test_unconfigured_azp_is_503_not_a_silently_skipped_check(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2 shipped this as "checked when set". A check you can switch off by
    forgetting an env var is not a check — so an unset allow-list is now a
    configuration error, and a *valid* token gets 503 rather than a pass."""
    monkeypatch.delenv(deps.AUTHORIZED_PARTIES_ENV, raising=False)
    with pytest.raises(Exception) as excinfo:
        deps.verify_token(_sign(signing_key, _claims()))
    assert excinfo.value.status_code == 503  # type: ignore[attr-defined]
    assert deps.AUTHORIZED_PARTIES_ENV in str(excinfo.value.detail)  # type: ignore[attr-defined]


def test_wrong_azp_is_401_when_configured(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(deps.AUTHORIZED_PARTIES_ENV, f"{ORIGIN},https://alphadesk.vercel.app")
    token = _sign(signing_key, _claims(azp="https://evil.example"))
    assert "different origin" in _assert_401(deps.verify_token, token)


def test_matching_azp_passes_when_configured(
    jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(deps.AUTHORIZED_PARTIES_ENV, f"https://other.example, {ORIGIN}")
    assert deps.verify_token(_sign(signing_key, _claims()))["sub"] == USER_ID


# --------------------------------------------------------------------------- #
# Fail-closed configuration
# --------------------------------------------------------------------------- #
def test_an_unreachable_jwks_endpoint_is_503_not_401(
    jwks_server: _JwksServer,
    signing_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clerk being down is our outage, not the caller's bad token.

    A 401 here would send a perfectly-signed-in user off to re-authenticate
    against the very service that is unreachable, forever.
    """

    def _down(_self: PyJWKClient) -> dict[str, Any]:
        raise PyJWKClientConnectionError("connection refused")

    monkeypatch.setattr(PyJWKClient, "fetch_data", _down)
    with pytest.raises(Exception) as excinfo:
        deps.verify_token(_sign(signing_key, _claims()))
    assert excinfo.value.status_code == 503  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "missing",
    [deps.JWKS_URL_ENV, deps.ISSUER_ENV, deps.AUTHORIZED_PARTIES_ENV],
)
def test_unconfigured_clerk_is_503_not_401(
    jwks_server: _JwksServer,
    signing_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    """"This server was never configured" must not masquerade as "your token is bad"."""
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(Exception) as excinfo:
        deps.verify_token(_sign(signing_key, _claims()))
    assert excinfo.value.status_code == 503  # type: ignore[attr-defined]
    assert missing in str(excinfo.value.detail)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Email extraction
# --------------------------------------------------------------------------- #
def test_email_is_none_when_the_token_carries_none() -> None:
    assert deps.claim_email(_claims()) is None


@pytest.mark.parametrize("key", ["email", "email_address", "primary_email_address"])
def test_email_is_read_from_any_of_the_usual_claim_names(key: str) -> None:
    assert deps.claim_email(_claims(**{key: " who@example.com "})) == "who@example.com"


# --------------------------------------------------------------------------- #
# The dependency, over HTTP, against the real database
# --------------------------------------------------------------------------- #
@pytest.fixture
def app_with_current_user(db_session: AsyncSession) -> FastAPI:
    """A one-route app whose only job is to report who the caller is."""
    app = FastAPI()

    @app.get("/me")
    async def me(user_id: str = Depends(deps.current_user)) -> dict[str, str]:
        return {"user_id": user_id}

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[async_session] = _session
    return app


@pytest_asyncio.fixture
async def client(app_with_current_user: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app_with_current_user), base_url="http://testserver"
    ) as http:
        yield http


def _auth(key: rsa.RSAPrivateKey, **overrides: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {_sign(key, _claims(**overrides))}"}


async def test_valid_token_identifies_the_user(
    client: AsyncClient, jwks_server: _JwksServer, signing_key: rsa.RSAPrivateKey
) -> None:
    response = await client.get("/me", headers=_auth(signing_key))
    assert response.status_code == 200
    assert response.json() == {"user_id": USER_ID}


async def test_first_sight_creates_the_users_row(
    client: AsyncClient,
    jwks_server: _JwksServer,
    signing_key: rsa.RSAPrivateKey,
    db_session: AsyncSession,
) -> None:
    assert (await db_session.execute(select(User))).scalars().all() == []

    await client.get("/me", headers=_auth(signing_key, email="who@example.com"))

    users = (await db_session.execute(select(User))).scalars().all()
    assert [(u.id, u.email) for u in users] == [(USER_ID, "who@example.com")]
    # `created_at` is NOT NULL and its default lives on the *model*, which a
    # Core insert never consults — so this assertion is the difference between
    # a working first sign-in and an IntegrityError on it.
    assert users[0].created_at is not None
    assert users[0].created_at.tzinfo is not None


async def test_a_token_without_an_email_claim_stores_a_null_email(
    client: AsyncClient,
    jwks_server: _JwksServer,
    signing_key: rsa.RSAPrivateKey,
    db_session: AsyncSession,
) -> None:
    """A default Clerk session token has no email — that must not be an error."""
    assert (await client.get("/me", headers=_auth(signing_key))).status_code == 200
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.email is None


async def test_the_row_is_written_once_not_once_per_request(
    client: AsyncClient,
    jwks_server: _JwksServer,
    signing_key: rsa.RSAPrivateKey,
    db_session: AsyncSession,
) -> None:
    """Three requests, one insert — proven by deleting the row underneath.

    A second `INSERT ... ON CONFLICT DO NOTHING` would be invisible in a row
    count, so the row is removed out-of-band between requests: if the dependency
    still hit the database, it would come back. It must not — and after
    `reset_seen_users()` it must, which is what shows the absence is the cache
    doing its job rather than the insert being broken.
    """
    for _ in range(3):
        assert (await client.get("/me", headers=_auth(signing_key))).status_code == 200
    assert len((await db_session.execute(select(User))).scalars().all()) == 1

    await db_session.execute(text("DELETE FROM users"))
    await db_session.commit()

    assert (await client.get("/me", headers=_auth(signing_key))).status_code == 200
    assert (await db_session.execute(select(User))).scalars().all() == []

    deps.reset_seen_users()
    assert (await client.get("/me", headers=_auth(signing_key))).status_code == 200
    assert (await db_session.execute(select(User))).scalar_one().id == USER_ID


async def test_two_users_each_get_a_row(
    client: AsyncClient,
    jwks_server: _JwksServer,
    signing_key: rsa.RSAPrivateKey,
    db_session: AsyncSession,
) -> None:
    await client.get("/me", headers=_auth(signing_key, sub="user_aaa"))
    await client.get("/me", headers=_auth(signing_key, sub="user_bbb"))
    ids = sorted(
        u.id for u in (await db_session.execute(select(User))).scalars().all()
    )
    assert ids == ["user_aaa", "user_bbb"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic dXNlcjpwdw=="},
    ],
)
async def test_a_rejected_request_creates_no_user_row(
    client: AsyncClient,
    jwks_server: _JwksServer,
    db_session: AsyncSession,
    headers: dict[str, str],
) -> None:
    response = await client.get("/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert (await db_session.execute(select(User))).scalars().all() == []


async def test_an_expired_token_creates_no_user_row(
    client: AsyncClient,
    jwks_server: _JwksServer,
    signing_key: rsa.RSAPrivateKey,
    db_session: AsyncSession,
) -> None:
    now = int(time.time())
    headers = _auth(signing_key, iat=now - 7200, nbf=now - 7200, exp=now - 60)
    assert (await client.get("/me", headers=headers)).status_code == 401
    assert (await db_session.execute(select(User))).scalars().all() == []
