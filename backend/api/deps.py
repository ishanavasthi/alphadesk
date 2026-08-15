"""Who is calling? — the Clerk-backed `current_user` FastAPI dependency (card F2).

This module is the **only** place AlphaDesk decides that a request belongs to a
person. It takes a Clerk session token off `Authorization: Bearer <jwt>`,
verifies it, and hands back the Clerk `user_id` (the token's `sub`). Nothing
here reads a cookie, a query parameter, or a header a browser sets on its own.

Deliberately **not wired into any endpoint by this card.** F2 lands identity and
its tests; F3 (per-user broker links) and F4 are the first consumers. Wiring it
into `/portfolio/*` while the interim C0 admin secret is still the live gate
would lock the operator out of their own dashboard before Clerk keys exist.

## What "verified" means here

Clerk session tokens are RS256 JWTs signed by the instance's own key pair. The
public half is published as a JWKS document at
`https://<frontend-api>/.well-known/jwks.json`, and that is the only network
call in the whole path — `PyJWKClient` caches the key set for `lifespan`
seconds, so steady-state verification is a local signature check with **no**
round-trip to Clerk. That is the property the docs call "networkless", and it
is why this file uses PyJWT rather than `clerk-backend-api`: the SDK's
`authenticate_request()` wants a `CLERK_SECRET_KEY` and an httpx `Request`
object to hand it a networkless verification of the same JWT.

Checks applied, in order:

1. `Authorization: Bearer <token>` present and non-empty         -> else 401
2. `kid` in the header resolves against the cached JWKS          -> else 401
3. signature verifies under **RS256 only** — `algorithms=["RS256"]`
   is what makes `alg: none` and an HS256 confusion attack fail  -> else 401
4. `exp` / `nbf` / `iat` inside their windows                    -> else 401
5. `iss` equals `CLERK_ISSUER` exactly                           -> else 401
6. `azp` in `CLERK_AUTHORIZED_PARTIES`, when that is configured  -> else 401
7. `sub` present and non-empty                                   -> else 401

Step 6 is optional because a single-origin deployment has nothing to compare
against yet, but Clerk's own manual-verification guide is blunt about it: "not
setting this value can open your application to CSRF attacks." Set it in any
environment that has a known frontend origin.

## Fail-closed configuration

`CLERK_JWKS_URL` and `CLERK_ISSUER` are required. Unset, every call answers
**503**, never 200 and never a 401 — a 401 would read as "your token is bad"
when the truth is "this server was never configured", and an operator would go
hunting in the wrong place. Same convention as S1's `CRON_SECRET`.

## The `users` row

The first time a token for a given `sub` verifies, a `users` row is inserted
(`ON CONFLICT DO NOTHING`, so two concurrent first requests cannot collide).
Later requests for the same `sub` skip the database entirely — see
`_SEEN_USERS`. Consequences worth knowing:

- `email` is captured **at first sight only**. A user who later changes their
  email in Clerk keeps the old value here until something explicitly syncs it
  (a Clerk webhook, a future card). The Clerk `user_id` is the identity; the
  email column is a convenience for humans reading the table.
- Deleting a row from `users` out-of-band does not make the next request
  recreate it within the same process, because the id is cached. Restart the
  app (or call `reset_seen_users()`) after a manual delete.
"""

from __future__ import annotations

import asyncio
import os
from typing import Annotated, Any, Final

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, utcnow
from db.session import async_session

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
JWKS_URL_ENV: Final = "CLERK_JWKS_URL"
ISSUER_ENV: Final = "CLERK_ISSUER"
AUTHORIZED_PARTIES_ENV: Final = "CLERK_AUTHORIZED_PARTIES"

#: Clerk signs session tokens with RS256 and nothing else. Pinning the list is
#: what rejects `alg: none` and the "sign it HS256 with the public key" trick.
ALGORITHMS: Final = ["RS256"]

#: How long a fetched JWKS document is reused before it is re-fetched. Clerk
#: rotates signing keys rarely and publishes the new key alongside the old one,
#: so five minutes of staleness costs nothing and buys a networkless path.
JWKS_LIFESPAN_SECONDS: Final = 300

_UNCONFIGURED_MSG: Final = (
    f"Clerk is not configured on this server: set {JWKS_URL_ENV} "
    f"(https://<your-frontend-api>/.well-known/jwks.json) and {ISSUER_ENV} "
    "(https://<your-frontend-api>). Both come from the Clerk Dashboard -> "
    "Configure -> API keys."
)


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def authorized_parties() -> list[str]:
    """Origins allowed in the token's `azp` claim; empty means "do not check"."""
    raw = _env(AUTHORIZED_PARTIES_ENV) or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


# --------------------------------------------------------------------------- #
# JWKS client (cached per JWKS URL)
# --------------------------------------------------------------------------- #
_jwk_clients: dict[str, PyJWKClient] = {}


def get_jwk_client() -> PyJWKClient:
    """The process-wide `PyJWKClient` for the configured JWKS URL.

    Cached **per URL** rather than in a single slot so that a test (or a config
    reload) pointing at a different JWKS does not silently keep serving keys
    fetched from the previous one.
    """
    url = _env(JWKS_URL_ENV)
    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNCONFIGURED_MSG
        )
    client = _jwk_clients.get(url)
    if client is None:
        client = PyJWKClient(
            url,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=JWKS_LIFESPAN_SECONDS,
            timeout=10,
        )
        _jwk_clients[url] = client
    return client


def reset_jwk_clients() -> None:
    """Drop every cached JWKS client. For tests and config reloads."""
    _jwk_clients.clear()


# --------------------------------------------------------------------------- #
# Token verification
# --------------------------------------------------------------------------- #
def _unauthorized(detail: str) -> HTTPException:
    """401 with the `WWW-Authenticate` header the Bearer scheme requires."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def bearer_token(authorization: str | None) -> str:
    """Pull the token out of an `Authorization` header, or raise 401.

    The scheme match is case-insensitive because RFC 7235 says the scheme is,
    and clients in the wild send `bearer` as often as `Bearer`.
    """
    if not authorization:
        raise _unauthorized("Missing Authorization header.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Authorization header must be 'Bearer <token>'.")
    return token.strip()


def verify_token(token: str) -> dict[str, Any]:
    """Verify a Clerk session token and return its claims. Raises 401 / 503.

    Synchronous on purpose: everything except the first JWKS fetch is CPU-bound
    signature maths. `current_user` runs it off the event loop.
    """
    issuer = _env(ISSUER_ENV)
    if not issuer:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNCONFIGURED_MSG
        )

    client = get_jwk_client()
    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except PyJWKClientConnectionError as exc:
        # The JWKS endpoint is unreachable. That is our problem, not the
        # caller's — answering 401 would send them off to re-authenticate
        # against a service we simply failed to talk to.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot reach the Clerk JWKS endpoint ({type(exc).__name__}).",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - unknown kid, unparseable header
        raise _unauthorized(
            f"Cannot resolve a signing key for this token ({type(exc).__name__})."
        ) from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            issuer=issuer,
            # Clerk session tokens carry no `aud` by default; `azp` is the
            # authorized-party claim and is checked separately below.
            options={
                "verify_aud": False,
                "require": ["exp", "iat", "iss", "sub"],
            },
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized(f"Invalid token ({type(exc).__name__}).") from exc

    allowed = authorized_parties()
    if allowed and claims.get("azp") not in allowed:
        raise _unauthorized("Token was issued for a different origin (azp).")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise _unauthorized("Token has no subject (sub).")

    return claims


# --------------------------------------------------------------------------- #
# Lazy `users` upsert
# --------------------------------------------------------------------------- #
#: Clerk user ids already known to exist in `users` **in this process**. Purely
#: a write-avoidance cache: the insert underneath is `ON CONFLICT DO NOTHING`,
#: so losing this set on restart costs one redundant statement per user, never
#: correctness.
_SEEN_USERS: set[str] = set()

#: Cap so a long-lived process serving many users cannot grow this without
#: bound. On overflow the whole set is dropped rather than evicting one entry:
#: the only cost is a round of no-op inserts, and an LRU here would be machinery
#: guarding a statement that is already idempotent.
_SEEN_USERS_MAX: Final = 10_000


def reset_seen_users() -> None:
    """Forget which users this process has already inserted. For tests."""
    _SEEN_USERS.clear()


async def ensure_user(session: AsyncSession, user_id: str, email: str | None) -> None:
    """Insert `user_id` into `users` if this process has not already done so.

    `ON CONFLICT (id) DO NOTHING` rather than a SELECT-then-INSERT: two requests
    from the same brand-new user arriving together would both find no row and
    both insert, and one of them would get an `IntegrityError` on a path that
    has nothing to do with the request it is serving.
    """
    if user_id in _SEEN_USERS:
        return

    # `created_at` is filled explicitly: `User.created_at`'s `default_factory`
    # is a *model* default, and this is a Core insert against the table, which
    # never sees it. The column is NOT NULL, so omitting it is not a silently
    # wrong timestamp — it is an IntegrityError on every first sign-in.
    values: dict[str, Any] = {"id": user_id, "created_at": utcnow()}
    if email:
        values["email"] = email
    await session.execute(
        pg_insert(User.__table__).values(**values).on_conflict_do_nothing(index_elements=["id"])
    )
    await session.commit()

    if len(_SEEN_USERS) >= _SEEN_USERS_MAX:
        _SEEN_USERS.clear()
    _SEEN_USERS.add(user_id)


# --------------------------------------------------------------------------- #
# The dependency
# --------------------------------------------------------------------------- #
def claim_email(claims: dict[str, Any]) -> str | None:
    """Best-effort email from a Clerk session token.

    A default Clerk session token carries **no** email claim — it is a
    deliberately small token. An instance whose JWT template adds `email` (or
    `email_address`, or a nested `primary_email_address`) gets it stored;
    everything else stores NULL, which is a fine state for this column.
    """
    for key in ("email", "email_address", "primary_email_address"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def current_user(
    # `session` comes first because it has no default — Python's rule, not a
    # preference. Callers never pass either argument; FastAPI fills both.
    session: Annotated[AsyncSession, Depends(async_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """The Clerk `user_id` behind this request. 401 if there isn't a valid one.

        @router.get("/whatever")
        async def handler(user_id: Annotated[str, Depends(current_user)]):
            ...

    Verification runs in a worker thread: the first call per process fetches the
    JWKS over the network, and RSA verification is CPU work either way. Neither
    belongs on the event loop.
    """
    token = bearer_token(authorization)
    claims = await asyncio.to_thread(verify_token, token)
    user_id: str = claims["sub"]
    await ensure_user(session, user_id, claim_email(claims))
    return user_id


#: Ready-made annotation so call sites read as `user_id: CurrentUser`.
CurrentUser = Annotated[str, Depends(current_user)]


__all__ = [
    "ALGORITHMS",
    "AUTHORIZED_PARTIES_ENV",
    "CurrentUser",
    "ISSUER_ENV",
    "JWKS_URL_ENV",
    "authorized_parties",
    "bearer_token",
    "claim_email",
    "current_user",
    "ensure_user",
    "get_jwk_client",
    "reset_jwk_clients",
    "reset_seen_users",
    "verify_token",
]
