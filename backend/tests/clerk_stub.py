"""A self-contained Clerk stand-in: one RSA key pair, its JWKS, and a signer.

A Clerk session token is an ordinary RS256 JWT whose public half is published as
a JWKS document, so a suite that mints its own key pair exercises every code
path in `api.deps` except "did Clerk really issue this". That one is covered by
the live check in `docs/TESTING/F3.md`, against the real instance.

`tests/test_auth_deps.py` keeps its own copy of these helpers (it predates this
module and pins subtly different things, like the fetch counter). This one exists
for the F3 suites that need a *signed-in caller* rather than a token to dissect.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm

from api import deps

ISSUER = "https://leading-sheepdog-6215.clerk.accounts.dev"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
KID = "ins_f3TeStKeYiD"
ORIGIN = "http://localhost:3000"


def jwks_document(key: rsa.RSAPrivateKey, kid: str = KID) -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


def sign(key: rsa.RSAPrivateKey, claims: dict[str, Any], kid: str = KID) -> str:
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


def session_claims(user_id: str, **overrides: Any) -> dict[str, Any]:
    """A plausible Clerk **session** token payload — `sid` included, since F3
    rejects anything without it."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": user_id,
        "iat": now,
        "nbf": now - 5,
        "exp": now + 3600,
        "azp": ORIGIN,
        "sid": f"sess_{user_id[-8:]}",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


@pytest.fixture(scope="session")
def clerk_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def clerk(
    clerk_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> Iterator[rsa.RSAPrivateKey]:
    """Serve our JWKS to `PyJWKClient` and set the env a real instance would."""
    document = jwks_document(clerk_key)

    def fetch_data(_self: Any = None) -> dict[str, Any]:
        return document

    monkeypatch.setattr(PyJWKClient, "fetch_data", fetch_data)
    monkeypatch.setenv(deps.JWKS_URL_ENV, JWKS_URL)
    monkeypatch.setenv(deps.ISSUER_ENV, ISSUER)
    monkeypatch.setenv(deps.AUTHORIZED_PARTIES_ENV, ORIGIN)
    deps.reset_jwk_clients()
    deps.reset_seen_users()
    yield clerk_key
    deps.reset_jwk_clients()
    deps.reset_seen_users()


def bearer(key: rsa.RSAPrivateKey, user_id: str, **overrides: Any) -> dict[str, str]:
    """`Authorization` header for a signed-in `user_id`."""
    return {"Authorization": f"Bearer {sign(key, session_claims(user_id, **overrides))}"}


__all__ = [
    "ISSUER",
    "JWKS_URL",
    "KID",
    "ORIGIN",
    "bearer",
    "clerk",
    "clerk_key",
    "jwks_document",
    "session_claims",
    "sign",
]
