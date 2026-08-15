"""Who is calling? — the Clerk-backed `current_user` FastAPI dependency.

This module is the **only** place AlphaDesk decides that a request belongs to a
person. It takes a Clerk session token off `Authorization: Bearer <jwt>`,
verifies it, and hands back the Clerk `user_id` (the token's `sub`). Nothing
here reads a cookie, a query parameter, or a header a browser sets on its own.

Landed by **F2** with no consumers; wired up by **F3**, which is also where the
three latent findings from F2's review were fixed (see below). Its callers now
are `/auth/login`, `/auth/logout`, `/auth/status` and every `/portfolio/*`
route — the last of which still accepts the interim C0 admin secret as an
alternative until card L1 turns sign-in on in production.

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
6. `azp` in `CLERK_AUTHORIZED_PARTIES`, which is **mandatory**   -> else 401
7. `sub` present and non-empty                                   -> else 401
8. `sid` present — this must be a *session* token                -> else 401

### F3 hardening (the three latent findings from F2's review)

**`CLERK_AUTHORIZED_PARTIES` is no longer optional.** F2 shipped it as
"checked when configured", which is a check that silently does nothing on the
deployment that most needs it. Clerk's own manual-verification guide is blunt —
"not setting this value can open your application to CSRF attacks" — so an unset
value now answers **503** at auth time, exactly like an unset issuer. A gate
that can be disabled by forgetting to set an environment variable is not a gate.

**`sid` is required.** Clerk mints two kinds of RS256 JWT from the same key
pair: short-lived *session* tokens (which carry `sid`) and instance JWT-template
tokens, which can be minted for other purposes and can be long-lived. Both
verify identically against the JWKS. Requiring `sid` is what keeps a
template-issued token from authenticating a request here.

**Unknown `kid`s cannot drive outbound fetches.** `PyJWKClient.get_signing_key`
refreshes the JWK set whenever a `kid` misses, so a stream of tokens with random
`kid`s turned into a 1:1 stream of requests to Clerk from our IP — an
amplification primitive pointed at our own identity provider. `_resolve_key`
below refreshes at most once per :data:`UNKNOWN_KID_COOLDOWN_SECONDS` no matter
how many distinct unknown `kid`s arrive, so a genuine key rotation is still
picked up within seconds while an attacker gets nothing. A test pins the fetch
count.

## Fail-closed configuration

`CLERK_JWKS_URL`, `CLERK_ISSUER` and `CLERK_AUTHORIZED_PARTIES` are required.
Unset, every call answers **503**, never 200 and never a 401 — a 401 would read
as "your token is bad" when the truth is "this server was never configured", and
an operator would go hunting in the wrong place. Same convention as S1's
`CRON_SECRET`. An unreachable **or unparseable** JWKS document is 503 for the
same reason: a document we cannot read is our failure, not the caller's.

## Order of operations

The token is verified **before** any database dependency is resolved. A request
with a missing or malformed token must answer 401 even on a deployment whose
database is down — resolving a session first would turn "your token is bad" into
a 500 and hand an unauthenticated caller a liveness oracle on our Postgres.

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
import time
from typing import Annotated, Any, Final

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWK, PyJWKClient, PyJWKSet
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWKSetError
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

#: How long a JWKS refresh triggered by an *unknown* `kid` suppresses the next
#: one. Short enough that a real key rotation is picked up almost immediately,
#: long enough that a flood of random `kid`s costs the attacker everything and
#: us one request.
UNKNOWN_KID_COOLDOWN_SECONDS: Final = 30

_UNCONFIGURED_MSG: Final = (
    f"Clerk is not configured on this server: set {JWKS_URL_ENV} "
    f"(https://<your-frontend-api>/.well-known/jwks.json) and {ISSUER_ENV} "
    "(https://<your-frontend-api>). Both come from the Clerk Dashboard -> "
    "Configure -> API keys."
)

_NO_AZP_MSG: Final = (
    f"Clerk is not configured on this server: set {AUTHORIZED_PARTIES_ENV} to "
    "the frontend origin(s) allowed to use this API, comma-separated (e.g. "
    "https://alphadesk.vercel.app,http://localhost:3000). It is required — an "
    "unset value would mean accepting a token minted for any other site."
)


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def authorized_parties() -> list[str]:
    """Origins allowed in the token's `azp` claim. Empty means **unconfigured**.

    F2 treated empty as "skip the check". F3 treats it as a misconfiguration —
    see :func:`require_authorized_parties`.
    """
    raw = _env(AUTHORIZED_PARTIES_ENV) or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def require_authorized_parties() -> list[str]:
    """The configured `azp` allow-list, or 503. Never an empty list."""
    allowed = authorized_parties()
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NO_AZP_MSG
        )
    return allowed


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


#: Per-JWKS-URL timestamp of the last refresh an unknown `kid` provoked.
_last_unknown_kid_refresh: dict[str, float] = {}

#: The parsed key set per JWKS URL, with the monotonic clock reading it was
#: fetched at. Cached here rather than inside `PyJWKClient` because this module
#: needs to answer "was that fetch avoidable?" precisely — see `_resolve_key`.
#: `PyJWKClient` is kept purely as the fetcher, so its connection-error typing
#: and its timeout still apply.
_jwk_sets: dict[str, tuple[float, PyJWKSet]] = {}


def reset_jwk_clients() -> None:
    """Drop every cached JWKS client and key set. For tests and config reloads."""
    _jwk_clients.clear()
    _jwk_sets.clear()
    _last_unknown_kid_refresh.clear()


def _jwk_set(client: PyJWKClient, url: str, *, refresh: bool) -> PyJWKSet:
    """The key set for `url`, from cache unless it is stale or `refresh`."""
    entry = _jwk_sets.get(url)
    if not refresh and entry is not None:
        age = time.monotonic() - entry[0]
        if age < JWKS_LIFESPAN_SECONDS:
            return entry[1]
    jwk_set = PyJWKSet.from_dict(client.fetch_data())
    _jwk_sets[url] = (time.monotonic(), jwk_set)
    return jwk_set


def _match_kid(jwk_set: PyJWKSet, kid: str) -> PyJWK | None:
    for key in jwk_set.keys:
        if key.key_id == kid:
            return key
    return None


def _token_kid(token: str) -> str | None:
    """The `kid` from the token header, or None if there isn't a readable one."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return None
    kid = header.get("kid")
    return kid if isinstance(kid, str) and kid else None


def _resolve_key(client: PyJWKClient, url: str, token: str) -> PyJWK:
    """Find the signing key for `token`, refreshing the JWK set at most rarely.

    This replaces `PyJWKClient.get_signing_key_from_jwt`, whose contract is
    "refresh on every miss". That is the right default for a library and the
    wrong one for a public endpoint: the miss is attacker-controlled, so the
    refresh is too, and every unknown `kid` became one outbound request to
    Clerk. Here a miss refreshes only if no miss has refreshed in the last
    :data:`UNKNOWN_KID_COOLDOWN_SECONDS`; inside that window an unknown `kid` is
    simply a 401 with no network at all.

    A rotated key is still picked up: the new `kid` misses, the cooldown has
    long since lapsed for an idle instance, and the refresh happens on that
    first real request.
    """
    kid = _token_kid(token)
    if kid is None:
        raise _unauthorized("Token header carries no key id (kid).")

    match = _match_kid(_jwk_set(client, url, refresh=False), kid)
    if match is not None:
        return match

    now = time.monotonic()
    last = _last_unknown_kid_refresh.get(url, float("-inf"))
    if now - last < UNKNOWN_KID_COOLDOWN_SECONDS:
        raise _unauthorized("Cannot resolve a signing key for this token (unknown kid).")

    _last_unknown_kid_refresh[url] = now
    match = _match_kid(_jwk_set(client, url, refresh=True), kid)
    if match is None:
        raise _unauthorized("Cannot resolve a signing key for this token (unknown kid).")
    return match


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
    # Read before the signature check so a deployment that forgot the allow-list
    # answers 503 rather than quietly accepting every origin's tokens.
    allowed = require_authorized_parties()

    url = _env(JWKS_URL_ENV) or ""
    client = get_jwk_client()
    try:
        signing_key = _resolve_key(client, url, token)
    except HTTPException:
        raise
    except PyJWKClientConnectionError as exc:
        # The JWKS endpoint is unreachable. That is our problem, not the
        # caller's — answering 401 would send them off to re-authenticate
        # against a service we simply failed to talk to.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot reach the Clerk JWKS endpoint ({type(exc).__name__}).",
        ) from exc
    except (PyJWKSetError, ValueError) as exc:
        # We reached the endpoint and could not make a key set out of what came
        # back (not JSON, no `keys`, keys of a kind we cannot load). Same
        # reasoning as unreachable: a caller cannot fix our identity provider
        # serving garbage, and a 401 would send them to re-authenticate against
        # it. `ValueError` covers the JSON decode, which PyJWT lets escape raw.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The Clerk JWKS document is unusable ({type(exc).__name__}).",
        ) from exc
    except PyJWKClientError as exc:
        raise _unauthorized(
            f"Cannot resolve a signing key for this token ({type(exc).__name__})."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - unparseable header, unknown key type
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

    if claims.get("azp") not in allowed:
        raise _unauthorized("Token was issued for a different origin (azp).")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise _unauthorized("Token has no subject (sub).")

    # Session-token evidence. Clerk signs JWT-template tokens with the same key
    # pair as session tokens, and a template token can be long-lived and minted
    # for an entirely different audience. `sid` is what a session token has and
    # a template token does not, so requiring it is what keeps this endpoint
    # from accepting the wrong kind of validly-signed JWT.
    session_id = claims.get("sid")
    if not isinstance(session_id, str) or not session_id.strip():
        raise _unauthorized("Token is not a session token (no sid).")

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


async def verified_claims(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """The verified claims of the request's bearer token. 401/503, never 200.

    Split out from :func:`current_user` so it can be depended on **first**.
    FastAPI resolves a dependency's sub-dependencies in declaration order, so
    with this ahead of the session a bad or missing token 401s before anything
    opens a database connection. The old signature had `session` first (Python
    forced it: it was the parameter without a default), which meant an
    unauthenticated request to a deployment whose Postgres was down answered 500
    — a worse answer, and a free liveness probe on our database for anyone with
    a garbage token.

    Verification runs in a worker thread: the first call per process fetches the
    JWKS over the network, and RSA verification is CPU work either way. Neither
    belongs on the event loop.
    """
    token = bearer_token(authorization)
    return await asyncio.to_thread(verify_token, token)


async def current_user(
    claims: Annotated[dict[str, Any], Depends(verified_claims)],
    session: Annotated[AsyncSession, Depends(async_session)],
) -> str:
    """The Clerk `user_id` behind this request. 401 if there isn't a valid one.

        @router.get("/whatever")
        async def handler(user_id: Annotated[str, Depends(current_user)]):
            ...
    """
    user_id: str = claims["sub"]
    email = claim_email(claims)
    await ensure_user(session, user_id, email)
    await _maybe_adopt(session, user_id, email)
    return user_id


async def _maybe_adopt(session: AsyncSession, user_id: str, email: str | None) -> None:
    """Hand the pre-F3 `"local"` data to its owner, once. Never fails a request.

    Gated on `ALPHADESK_OPERATOR_EMAIL` matching the signed-in user's verified
    primary address — see `services.adoption`, which owns the rule. Wrapped
    because adoption is a migration convenience: if it cannot run, the right
    outcome is a logged warning and a working sign-in, not a 500 on the one
    request that was supposed to rescue the history.
    """
    from services.adoption import maybe_adopt

    try:
        await maybe_adopt(session, user_id, email)
    except Exception:  # noqa: BLE001 - see above
        import logging

        logging.getLogger(__name__).warning("adoption check failed", exc_info=True)


#: Ready-made annotation so call sites read as `user_id: CurrentUser`.
CurrentUser = Annotated[str, Depends(current_user)]


__all__ = [
    "ALGORITHMS",
    "AUTHORIZED_PARTIES_ENV",
    "UNKNOWN_KID_COOLDOWN_SECONDS",
    "CurrentUser",
    "ISSUER_ENV",
    "JWKS_URL_ENV",
    "authorized_parties",
    "bearer_token",
    "claim_email",
    "current_user",
    "ensure_user",
    "get_jwk_client",
    "require_authorized_parties",
    "reset_jwk_clients",
    "reset_seen_users",
    "verified_claims",
    "verify_token",
]
