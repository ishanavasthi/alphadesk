"""Per-user OAuth for the IND Money MCP server (card F3).

Until F3 this module held **one** credential set for the whole process: a
module-level ``_Auth`` singleton hydrated from ``backend/.ind_money_token.json``.
On a shared deployment that is a cross-user leak by construction — whoever
pressed Connect linked *the server*, and every other visitor read their
portfolio. This file is the rewrite that ends it.

## The shape now

    AuthStore.for_user(user_id, source)   ->  one user's credentials

Each store is hydrated from that user's ``broker_links`` row, with the tokens
and the client secret held in the ``*_enc`` columns as Fernet ciphertext
(`db.crypto`). Plaintext is never written to a column, a file (outside
single-tenant dev), or a log line. Refresh and expiry logic is carried over from
the singleton **verbatim** — it was correct; only its scope was wrong.

Concurrency is per user: ``_lock_for()`` hands out one ``asyncio.Lock`` per
``(user_id, source)``, so one user's token refresh serializes against itself and
against nothing else. A global lock would have made every user wait on the
slowest broker round-trip in the process.

## The login dance

``begin_login`` and ``complete_login`` implement authorization-code + PKCE with
dynamic client registration. Two things changed with F3:

1. **State is bound to a user, server-side.** The in-memory ``_PENDING`` dict is
   now the ``oauth_pending`` table: ``state -> user_id`` plus the PKCE verifier
   and the (encrypted) client credentials. ``GET /auth/callback`` resolves the
   owner from ``state`` **alone** — no cookie, no header, nothing the browser
   that lands on the callback could have chosen. State is single-use (deleted in
   the same statement that reads it) and expires after
   :data:`STATE_TTL_SECONDS`.
2. **The registered client is reused.** C2 verified that per-user DCR is viable
   (`docs/ind_money_payloads.md` §Q5), so the ``client_id``/``client_secret``
   minted for a user are stored on their link row and reused on re-link;
   a fresh registration happens only when there is no stored client, when the
   redirect URI has changed, or when the stored client is **rejected** — a
   token-endpoint `invalid_client` clears the stored registration
   (`AuthStore.forget_client`) so the next press of Connect re-registers
   instead of looping through the same rejection forever.

Unlink revokes: ``AuthStore.logout()`` calls the discovery document's
``revocation_endpoint`` for the refresh token *before* deleting the row. RFC
7009 revocation kills **tokens**, not client registrations (C2) — the client
row goes with the link either way.

## Single-tenant dev

``ALPHADESK_SINGLE_TENANT=1`` is the operator's own machine and nothing else. It
is the **only** mode in which the ambient credential sources are read at all:

  1. ``IND_MONEY_MCP_TOKEN`` env — static bearer, no refresh.
  2. ``backend/.ind_money_token.json`` — the file cache, now a *hydration
     source* for ``user_id="local"`` only.
  3. ``IND_MONEY_OAUTH_*`` env (CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN).
  4. The Claude Code credential store (``~/.claude/.credentials.json``).

With the flag unset, none of them is consulted for anybody — the DB row is the
only thing that can authenticate a user. `backend/tests/test_ind_money_auth.py`
pins that.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import contextvars
import logging
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.crypto import TokenEncryptionError, decrypt_optional, encrypt_optional
from db.models import BrokerLink, OAuthPending, User, utcnow

log = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).resolve().parents[1] / ".ind_money_token.json"
_CLAUDE_CREDS = Path.home() / ".claude" / ".credentials.json"
_DEFAULT_TOKEN_URL = "https://mcp.indmoney.com/token"
_CLAUDE_PREFIX = "indmoney"
_RESOURCE = "https://mcp.indmoney.com/"

#: The connector key this module speaks for. One row per (user, source).
SOURCE = "ind_money"

#: The pre-F3 owner of every credential. Still the identity local single-tenant
#: dev runs as, and the ``user_id`` the operator's pre-F3 rows carry until
#: `services.adoption` moves them onto their Clerk id.
LOCAL_USER_ID = "local"

#: The user a Lab run (`POST /analyze`, card F4) is executing as. The research
#: pipeline's LangGraph tools ask the MCP for *market* data with no user in
#: their signature, so the caller's identity is carried here instead of being
#: threaded through every tool. ``analyze()`` binds it for the life of one run;
#: `ambient_user_id()` reads it, so those tool calls mint from the caller's own
#: ``AuthStore`` rather than any process-wide or "whoever linked first" grant.
#: A ContextVar (not a module global) so concurrent runs never see each other's
#: identity — each asyncio task inherits a snapshot of the context it was
#: spawned in.
_run_user: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "alphadesk_run_user", default=None
)


def bind_run_user(user_id: str) -> contextvars.Token:
    """Bind the current Lab run's identity; pass the token to :func:`unbind_run_user`."""
    return _run_user.set(user_id)


def unbind_run_user(token: contextvars.Token) -> None:
    """Undo a :func:`bind_run_user`, restoring the previous binding."""
    _run_user.reset(token)


#: Both scopes the server advertises in ``scopes_supported`` (C2 §Q5).
#: ``market:read`` is what the research pipeline needs and ``portfolio:read``
#: is what the dashboard needs; asking for one and discovering the other is
#: missing costs a full re-link.
DEFAULT_SCOPE = "portfolio:read market:read"

#: How long an ``oauth_pending`` row stays usable. Ten minutes is longer than
#: any honest login takes and short enough that a leaked authorization URL is
#: worthless by the time it is found.
STATE_TTL_SECONDS = 600

#: Seconds of remaining life below which an access token is treated as expired.
_EXPIRY_SKEW_SECONDS = 60


def _scope() -> str:
    """The scope string to request. Overridable, but both scopes by default."""
    return (os.environ.get("IND_MONEY_OAUTH_SCOPE") or DEFAULT_SCOPE).strip()


def single_tenant_mode() -> bool:
    """Whether this process runs in single-tenant (operator-owned) mode.

    Set ``ALPHADESK_SINGLE_TENANT=1`` for local development only. It enables the
    ambient credential fallbacks (env vars, the file cache, the Claude Code
    store) and bypasses the admin-secret gate on the interim paths. It must stay
    unset in every deployed environment — see V2_PLAN.md, card C0.
    """
    return os.environ.get("ALPHADESK_SINGLE_TENANT", "").strip().lower() in {"1", "true", "yes"}


class MCPAuthError(Exception):
    """Raised when a valid IND Money access token cannot be obtained.

    Base class covers *transient* failures too (network errors, 5xx), where the
    stored credentials may still be good and a later retry can succeed.
    """


class MCPAuthInvalid(MCPAuthError):
    """Raised when the stored credentials are *definitively* unusable.

    Missing refresh token / client id, or the token endpoint rejecting the
    refresh with a 4xx (e.g. ``invalid_grant``). Unlike a transient
    :class:`MCPAuthError`, this means reconnecting is required — callers should
    treat the session as logged out rather than retry.
    """


class OAuthStateError(MCPAuthError):
    """The callback's ``state`` is unknown, already used, or past its TTL.

    Its own class because the callback renders a *different page* for it: a
    reused or expired state must say "start again", never "we linked something".
    """


def _issuer_base() -> str:
    url = os.environ.get("IND_MONEY_MCP_URL") or "https://mcp.indmoney.com/mcp"
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


# --------------------------------------------------------------------------- #
# Database plumbing
# --------------------------------------------------------------------------- #
def database_configured() -> bool:
    """Whether a ``DATABASE_URL`` is set. Links cannot be stored without one."""
    return bool((os.environ.get("DATABASE_URL") or "").strip())


class _Session:
    """`async with _session() as s:` — an owned session, or None with no DB."""

    def __init__(self) -> None:
        self._ctx: Any = None

    async def __aenter__(self) -> Optional[AsyncSession]:
        if not database_configured():
            return None
        from db.session import get_sessionmaker

        self._ctx = get_sessionmaker()()
        return await self._ctx.__aenter__()

    async def __aexit__(self, *exc: Any) -> None:
        if self._ctx is not None:
            await self._ctx.__aexit__(*exc)
            self._ctx = None


def _session() -> _Session:
    return _Session()


async def ensure_user_row(session: AsyncSession, user_id: str) -> None:
    """`users` row for ``user_id``, if it is not there already.

    ``broker_links.user_id`` and ``oauth_pending.user_id`` are both FKs onto it,
    so a link written for a user nobody inserted is an ``IntegrityError`` at the
    worst possible moment — mid-OAuth-callback, with a one-use code already
    spent. `api.deps.current_user` inserts the row for a Clerk user; this covers
    ``"local"`` and any path that did not go through a verified token.
    """
    await session.execute(
        pg_insert(User.__table__)
        .values(id=user_id, created_at=utcnow())
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await session.commit()


#: OAuth 2.0 error codes that mean "the *client* is the problem", not the grant
#: (RFC 6749 §5.2). `unauthorized_client` is included because this server's
#: exact vocabulary is unverified and both readings point at the same recovery.
_CLIENT_ERROR_CODES = ("invalid_client", "unauthorized_client")


def _is_invalid_client(resp: httpx.Response) -> bool:
    """Whether a token-endpoint failure blames the registered client.

    RFC 6749 puts the code in a JSON `error` field, but a 401 on the token
    endpoint is *defined* as a client-authentication failure, so that alone
    counts. A body that is not JSON at all falls back to a substring check
    rather than throwing away the signal.
    """
    if resp.status_code == 401:
        return True
    if not 400 <= resp.status_code < 500:
        return False
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 - not every error body is JSON
        return any(code in resp.text for code in _CLIENT_ERROR_CODES)
    if isinstance(body, dict):
        return str(body.get("error") or "") in _CLIENT_ERROR_CODES
    return False


def _epoch(value: Optional[datetime]) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _as_datetime(epoch: float) -> Optional[datetime]:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
#: One lock per (user, source). Keyed rather than global so that user A's
#: refresh — a network round-trip to the broker — never blocks user B's.
_locks: Dict[Tuple[str, str], asyncio.Lock] = {}

#: One store per (user, source), so a hydrated set of credentials (and the fact
#: that a refresh was definitively rejected) survives between requests instead
#: of costing a DB read + Fernet decrypt on every MCP call.
_stores: Dict[Tuple[str, str], "AuthStore"] = {}

#: Ceiling on both caches. They hold **decrypted** tokens, so an unbounded one
#: is not merely a leak — it is a growing pile of plaintext credentials in a
#: long-lived process, and it also keeps serving a `"local"` store that adoption
#: has since moved out from under. On overflow both are dropped wholesale: the
#: cost is one DB read plus a decrypt per active user, and an LRU here would be
#: machinery guarding something already cheap and already idempotent.
_CACHE_MAX = 1000


def _evict_if_full() -> None:
    if len(_stores) >= _CACHE_MAX or len(_locks) >= _CACHE_MAX:
        # Locks go together with the stores: a lock kept for a store that no
        # longer exists protects nothing, and one dropped while its store lives
        # on would let two refreshes race.
        _stores.clear()
        _locks.clear()


def _lock_for(key: Tuple[str, str]) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        _evict_if_full()
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def reset_auth_stores() -> None:
    """Drop every cached store and lock. For tests and credential rotation."""
    _stores.clear()
    _locks.clear()


class AuthStore:
    """One user's IND Money credentials, backed by their ``broker_links`` row.

    Never construct this directly in application code — :meth:`for_user` is the
    entry point, and it is what keeps one store (and one lock) per user rather
    than a fresh, unsynchronized copy per request.
    """

    def __init__(self, user_id: str, source: str = SOURCE) -> None:
        if not user_id:
            raise ValueError("AuthStore requires a user_id; there is no ambient user")
        self.user_id = user_id
        self.source = source
        self._loaded = False
        self._access: Optional[str] = None
        self._refresh: Optional[str] = None
        self._expires_at: float = 0.0
        self._client_id: Optional[str] = None
        self._client_secret: Optional[str] = None
        self._redirect_uri: Optional[str] = None
        self._token_url: str = _DEFAULT_TOKEN_URL
        self._scope: Optional[str] = None
        self._static: Optional[str] = None
        #: Set when the source definitively rejected this credential. Surfaces
        #: as ``revoked`` in :meth:`status_verified`, which is what lets an idle
        #: status poll report `LinkHealth.REVOKED` instead of the softer
        #: "needs relink" (the M1/S1 carry).
        self._revoked = False
        #: Set when a link row exists but `TOKEN_ENCRYPTION_KEY` cannot read it.
        #: Distinct from `_revoked`: nothing was revoked, we just lost the key.
        self._undecryptable = False

    # ------------------------------------------------------------- factories
    @classmethod
    def for_user(cls, user_id: str, source: str = SOURCE) -> "AuthStore":
        """The process's store for ``(user_id, source)``, created on first use."""
        key = (user_id, source)
        store = _stores.get(key)
        if store is None:
            _evict_if_full()
            store = cls(user_id, source)
            _stores[key] = store
        return store

    @property
    def _key(self) -> Tuple[str, str]:
        return (self.user_id, self.source)

    def _is_local_dev(self) -> bool:
        """Whether the ambient (operator-owned) credential sources may be read.

        Both halves matter. ``single_tenant_mode()`` is the operator asserting
        this is their own machine; ``user_id == LOCAL_USER_ID`` keeps even that
        assertion from handing the operator's file cache to a *different* user
        id that happens to be asking on the same process.
        """
        return single_tenant_mode() and self.user_id == LOCAL_USER_ID

    # ------------------------------------------------------------- hydration
    async def ensure_loaded(self) -> None:
        if not self._loaded:
            await self._load()

    async def _load(self) -> None:
        """Fill this store from the DB row, then (dev only) the ambient sources."""
        local_dev = self._is_local_dev()
        self._undecryptable = False
        self._static = (os.environ.get("IND_MONEY_MCP_TOKEN") or None) if local_dev else None

        row = await self._read_row()
        if row is not None:
            self._hydrate_from_row(row)
        elif local_dev:
            self._hydrate_from_file()

        self._token_url = os.environ.get("IND_MONEY_OAUTH_TOKEN_URL", self._token_url)
        self._scope = self._scope or os.environ.get("IND_MONEY_OAUTH_SCOPE")

        if local_dev and not self._refresh:
            self._client_id = self._client_id or os.environ.get("IND_MONEY_OAUTH_CLIENT_ID")
            self._client_secret = self._client_secret or os.environ.get(
                "IND_MONEY_OAUTH_CLIENT_SECRET"
            )
            self._refresh = self._refresh or os.environ.get("IND_MONEY_OAUTH_REFRESH_TOKEN")
            if not self._refresh and _CLAUDE_CREDS.exists():
                self._seed_from_claude()

        self._loaded = True

    async def _read_row(self) -> Optional[BrokerLink]:
        async with _session() as session:
            if session is None:
                return None
            return await self._select_row(session)

    async def _select_row(self, session: AsyncSession) -> Optional[BrokerLink]:
        result = await session.execute(
            select(BrokerLink).where(
                BrokerLink.user_id == self.user_id, BrokerLink.source == self.source
            )
        )
        return result.scalars().first()

    def _hydrate_from_row(self, row: BrokerLink) -> None:
        """Fill this store from the link row, tolerating an unreadable one.

        A `TOKEN_ENCRYPTION_KEY` that was rotated or lost makes every stored
        credential undecryptable. That is a real operational state — the key is
        an env var on a Space that anyone can edit — and it used to escape as a
        bare `TokenEncryptionError` (a `RuntimeError`) from *every* endpoint
        that touches a link: `/auth/status`, `/auth/login`, `/auth/logout` and
        all of `/portfolio/*` answered **500**.

        A 500 is both the wrong status and the wrong story. The link is not
        broken at the source and the server is not confused about the request:
        we simply cannot read what we stored, and the fix is to re-link. So the
        row is treated as **unusable but present** — `needs_relink`, never
        `revoked` (nobody revoked anything) and never a crash.
        """
        self._expires_at = _epoch(row.expires_at)
        self._client_id = row.client_id
        self._redirect_uri = row.redirect_uri
        self._token_url = row.token_url or self._token_url
        self._scope = row.scope
        self._revoked = row.status == "revoked"
        try:
            self._access = decrypt_optional(row.access_token_enc)
            self._refresh = decrypt_optional(row.refresh_token_enc)
            self._client_secret = decrypt_optional(row.client_secret_enc)
        except TokenEncryptionError:
            log.warning(
                "broker link for %s cannot be decrypted with the current "
                "%s; treating it as needing a re-link",
                self.user_id,
                "TOKEN_ENCRYPTION_KEY",
            )
            self._undecryptable = True
            self._access = self._refresh = self._client_secret = None
            self._expires_at = 0.0
            # The stored client cannot be used without its secret, so the next
            # login registers a fresh one rather than failing at /token.
            self._client_id = None

    def _hydrate_from_file(self) -> None:
        """Read `backend/.ind_money_token.json` — **single-tenant dev only**.

        The file is the operator's own credential, written by the pre-F3 Connect
        flow. It stays readable so a dev machine that linked before this card
        keeps working; it is never consulted for a real (Clerk) user id, and
        never at all with ``ALPHADESK_SINGLE_TENANT`` unset.
        """
        if not _CACHE_FILE.exists():
            return
        try:
            d = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        self._access = d.get("access_token")
        self._refresh = d.get("refresh_token")
        self._expires_at = d.get("expires_at", 0.0)
        self._client_id = d.get("client_id")
        self._client_secret = d.get("client_secret")
        self._redirect_uri = d.get("redirect_uri")
        self._token_url = d.get("token_url") or self._token_url
        self._scope = d.get("scope")

    def _seed_from_claude(self) -> None:
        try:
            creds = json.loads(_CLAUDE_CREDS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        for key, v in (creds.get("mcpOAuth") or {}).items():
            if key.lower().startswith(_CLAUDE_PREFIX) and isinstance(v, dict):
                self._access = self._access or v.get("accessToken")
                self._refresh = self._refresh or v.get("refreshToken")
                self._client_id = self._client_id or v.get("clientId")
                self._scope = self._scope or v.get("scope")
                exp = v.get("expiresAt")
                if exp and not self._expires_at:
                    self._expires_at = exp / 1000.0 if exp > 1e12 else float(exp)
                return

    # ------------------------------------------------------------ persistence
    async def _persist(self, *, status: str = "active") -> None:
        """Write the current credentials back to ``broker_links``.

        Encrypted on the way in, always: the three ``*_enc`` columns are the
        only place a token, a refresh token or a client secret is allowed to
        come to rest.
        """
        async with _session() as session:
            if session is not None:
                await ensure_user_row(session, self.user_id)
                try:
                    values = self._encrypted_values(status)
                except TokenEncryptionError as exc:
                    # No key at all. Refusing loudly beats writing a row we
                    # could never read back, and beats a 500 — every caller of
                    # this treats MCPAuthError as "not linked right now".
                    log.error("cannot persist a broker link: %s", type(exc).__name__)
                    raise MCPAuthError(
                        "This server cannot store broker credentials: "
                        "TOKEN_ENCRYPTION_KEY is not set or is not a valid "
                        "Fernet key."
                    ) from exc
                stmt = pg_insert(BrokerLink.__table__).values(
                    linked_at=utcnow(), **values
                )
                await session.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_broker_links_user_source",
                        set_={k: getattr(stmt.excluded, k) for k in values},
                    )
                )
                await session.commit()

        if self._is_local_dev():
            self._persist_file()

    def _encrypted_values(self, status: str) -> Dict[str, Any]:
        """The row's column values, with every credential encrypted.

        Raises :class:`db.crypto.TokenEncryptionError` when there is no usable
        key — which is the one condition `_persist` has to turn into something
        other than a 500.
        """
        return {
            "user_id": self.user_id,
            "source": self.source,
            "access_token_enc": encrypt_optional(self._access),
            "refresh_token_enc": encrypt_optional(self._refresh),
            "expires_at": _as_datetime(self._expires_at),
            "client_id": self._client_id,
            "client_secret_enc": encrypt_optional(self._client_secret),
            "redirect_uri": self._redirect_uri,
            "token_url": self._token_url,
            "scope": self._scope,
            "supports_refresh": bool(self._refresh),
            "status": status,
            "last_refresh_at": utcnow(),
        }

    def _persist_file(self) -> None:
        """Mirror to the dev file cache. Single-tenant local only.

        Kept so that local development with no Postgres behaves exactly as it
        did before this card. On any deployment `_is_local_dev()` is False and
        this never runs.
        """
        try:
            _CACHE_FILE.write_text(
                json.dumps(
                    {
                        "access_token": self._access,
                        "refresh_token": self._refresh,
                        "expires_at": self._expires_at,
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "redirect_uri": self._redirect_uri,
                        "token_url": self._token_url,
                        "scope": self._scope,
                    }
                ),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    async def set_tokens(
        self,
        access: Optional[str],
        refresh: Optional[str],
        expires_in: Optional[int],
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        token_url: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> None:
        await self.ensure_loaded()
        self._access = access
        if refresh:
            self._refresh = refresh
        self._expires_at = time.time() + int(expires_in or 3600)
        if client_id:
            self._client_id = client_id
        if client_secret is not None:
            self._client_secret = client_secret
        if scope:
            self._scope = scope
        if token_url:
            self._token_url = token_url
        if redirect_uri:
            self._redirect_uri = redirect_uri
        self._static = None  # real OAuth tokens now own the chain
        self._revoked = False
        # A fresh link replaces whatever could not be decrypted, so the row is
        # readable again — otherwise re-linking, the advertised fix, would leave
        # the store insisting it is broken for the rest of the process.
        self._undecryptable = False
        await self._persist()

    async def _invalidate(self, *, clear_client: bool = False) -> None:
        """Drop the stored tokens so status reports a truthful logged-out state.

        Called when a refresh is definitively rejected (stale/revoked token) and
        on explicit logout. ``clear_client`` also forgets the registered OAuth
        client and deletes the link row entirely (used by logout); a plain
        invalidation keeps the client registration but zeroes the dead tokens
        and marks the row ``revoked``.
        """
        self._access = None
        self._refresh = None
        self._expires_at = 0.0
        self._static = None
        if clear_client:
            self._client_id = None
            self._client_secret = None
            self._redirect_uri = None
            self._scope = None
            self._revoked = False
            await self._delete_row()
            if self._is_local_dev():
                try:
                    _CACHE_FILE.unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
        else:
            self._revoked = True
            await self._persist(status="revoked")

    async def forget_client(self) -> None:
        """Drop the stored DCR client so the next login registers a fresh one.

        This is the recovery half of "reuse the registered client" (C2 §Q5).
        Reusing a client is right until the server stops accepting it — the
        registration was deleted, the secret was rotated, the vendor expired it
        — and at that point every login and every refresh fails identically
        forever, because the same dead `client_id` is loaded from the row each
        time. Clearing it converts a permanent failure into one extra
        registration.

        Deliberately does **not** touch the tokens: a rejected *client* says
        nothing about whether the refresh token is still good, and the caller
        may still be mid-flow.
        """
        log.warning(
            "IND Money rejected the stored OAuth client for %s; it will be "
            "re-registered on the next login",
            self.user_id,
        )
        self._client_id = None
        self._client_secret = None
        self._redirect_uri = None
        async with _session() as session:
            if session is None:
                return
            await session.execute(
                sa_update(BrokerLink)
                .where(
                    BrokerLink.user_id == self.user_id,
                    BrokerLink.source == self.source,
                )
                .values(client_id=None, client_secret_enc=None, redirect_uri=None)
            )
            await session.commit()

    async def _delete_row(self) -> None:
        async with _session() as session:
            if session is None:
                return
            await session.execute(
                sa_delete(BrokerLink).where(
                    BrokerLink.user_id == self.user_id, BrokerLink.source == self.source
                )
            )
            await session.commit()

    # ----------------------------------------------------------------- logout
    async def logout(self) -> Dict[str, object]:
        """Unlink: **revoke upstream first**, then delete the local row.

        Order is the whole point. Deleting our copy and calling it a disconnect
        would leave a live grant on the broker's side that the user has no way
        to see or reach — "we forgot your token" is not "your access is gone".
        An upstream failure still deletes locally (the user asked to be
        unlinked, and refusing would strand them) but is reported in the
        response so the UI can say so.
        """
        await self.ensure_loaded()
        refresh = self._refresh
        client_id, client_secret = self._client_id, self._client_secret
        revoked: Optional[bool] = None
        error: Optional[str] = None
        if refresh:
            try:
                revoked = await revoke_token(refresh, client_id, client_secret)
            except MCPAuthError as exc:
                revoked, error = False, str(exc)
                log.warning("unlink: upstream revocation failed for %s", self.user_id)

        await self._invalidate(clear_client=True)
        self._loaded = True
        return {
            "authenticated": False,
            "revoked_upstream": revoked,
            "revocation_error": error,
        }

    # ----------------------------------------------------------------- status
    def _describe(self) -> Dict[str, object]:
        now = time.time()
        if self._static:
            return {
                "authenticated": True,
                "source": "static",
                "expires_at": None,
                "expires_in_sec": None,
                "revoked": False,
                "undecryptable": False,
                "user_id": self.user_id,
            }
        authed = bool(self._access and self._expires_at - now > _EXPIRY_SKEW_SECONDS)
        return {
            "authenticated": authed,
            "source": "oauth" if authed else None,
            "expires_at": self._expires_at or None,
            "expires_in_sec": int(self._expires_at - now) if self._expires_at else None,
            "revoked": self._revoked,
            "undecryptable": self._undecryptable,
            "user_id": self.user_id,
        }

    def _logged_out(self, *, revoked: bool) -> Dict[str, object]:
        return {
            "authenticated": False,
            "source": None,
            "expires_at": None,
            "expires_in_sec": None,
            #: A stored link we cannot decrypt. Never `revoked` — nothing was
            #: revoked — and never a 500, which is what it used to be.
            "undecryptable": self._undecryptable,
            # The M1/S1 carry: a *definitive* rejection has to survive the trip
            # out of this function. Reporting it as a plain `authenticated:
            # False` is what made `link_health` answer NEEDS_RELINK forever on
            # an idle poll, when the truthful answer was REVOKED.
            "revoked": revoked,
            "user_id": self.user_id,
        }

    async def status_verified(self) -> Dict[str, object]:
        """Return a *truthful* auth status, refreshing an expired token if needed.

        A live access token (or a static bearer) returns immediately with no
        network call. If the access token is expired but a refresh token exists,
        this actually attempts the refresh: success reports authenticated with
        the new expiry; a definitive rejection clears the dead credentials and
        reports logged out **and revoked**; a transient failure reports logged
        out but keeps the tokens for a retry.
        """
        await self.ensure_loaded()
        if self._static:
            return self._describe()
        if self._undecryptable:
            # There is nothing to verify and nothing to refresh: the row is
            # there and unreadable. Say so, and do not overwrite it — the
            # operator may still restore the old key.
            return self._logged_out(revoked=False)
        if self._access and self._expires_at - time.time() > _EXPIRY_SKEW_SECONDS:
            return self._describe()
        # Access token missing/expired — verify we can actually mint one.
        try:
            await self.get_token()
        except MCPAuthInvalid:
            # Clear the dead credentials once; skip the write if already empty
            # (avoids rewriting the row on every logged-out status poll).
            if self._access or self._refresh or self._static:
                await self._invalidate()
            else:
                self._revoked = True
            return self._logged_out(revoked=True)
        except MCPAuthError:
            # Transient (network/5xx): keep creds, but report the truth for now.
            return self._logged_out(revoked=self._revoked)
        return self._describe()

    # ------------------------------------------------------------------ token
    async def get_token(self) -> str:
        if self._static:
            return self._static
        async with _lock_for(self._key):
            await self.ensure_loaded()
            if self._static:
                return self._static
            if self._access and (self._expires_at - time.time()) > _EXPIRY_SKEW_SECONDS:
                return self._access
            return await self._refresh_token()

    async def _refresh_token(self) -> str:
        if not self._refresh or not self._client_id:
            raise MCPAuthInvalid(
                "Not authenticated with IND Money. Use the Connect button to link "
                "this account."
            )
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh,
            "client_id": self._client_id,
        }
        if self._client_secret:
            data["client_secret"] = self._client_secret
        if self._scope:
            data["scope"] = self._scope
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    self._token_url, data=data, headers={"Accept": "application/json"}
                )
        except Exception as exc:  # noqa: BLE001
            raise MCPAuthError(f"IND Money token refresh request failed: {exc}")

        if resp.status_code != 200:
            # 4xx = the refresh token itself is bad/revoked -> definitive; the
            # caller must reconnect. 5xx = server hiccup -> transient, retryable.
            if _is_invalid_client(resp):
                # The *client*, not the grant, is what the server rejected —
                # the stored registration is dead. Forget it so the next login
                # registers a new one instead of failing the same way forever.
                await self.forget_client()
            err_cls = MCPAuthInvalid if 400 <= resp.status_code < 500 else MCPAuthError
            raise err_cls(
                f"IND Money token refresh failed ({resp.status_code}). "
                "Re-connect via the Connect button."
            )
        tok = resp.json()
        self._access = tok.get("access_token")
        if tok.get("refresh_token"):
            self._refresh = tok["refresh_token"]
        self._expires_at = time.time() + int(tok.get("expires_in", 3600))
        self._revoked = False
        await self._persist()
        if not self._access:
            raise MCPAuthError("IND Money token endpoint returned no access_token.")
        return self._access


# --------------------------------------------------------------------------- #
# Module-level entry points (per user)
# --------------------------------------------------------------------------- #
async def get_access_token(user_id: Optional[str] = None) -> str:
    """A valid IND Money bearer token for ``user_id``, refreshing if needed."""
    return await AuthStore.for_user(user_id or await ambient_user_id()).get_token()


async def auth_status(user_id: Optional[str] = None) -> Dict[str, object]:
    """Whether ``user_id`` is *actually* linked to IND Money.

    Verifies the token (refreshing an expired one) rather than trusting the mere
    presence of a refresh token, so an expired/revoked link reports as logged
    out instead of a false "connected".
    """
    return await AuthStore.for_user(user_id or await ambient_user_id()).status_verified()


async def logout(user_id: Optional[str] = None) -> Dict[str, object]:
    """Unlink ``user_id``: revoke upstream, then forget the credentials."""
    return await AuthStore.for_user(user_id or await ambient_user_id()).logout()


async def ambient_user_id() -> str:
    """Whose credentials a userless MCP call runs on.

    `tools/ind_money.py`'s market-data tools take no user in their signature —
    they ask the MCP for *quotes and movers*, not for anybody's holdings — so
    when a Lab run drives them the caller's identity has to reach them some other
    way. That way is :data:`_run_user`, bound by ``analyze()`` for the life of
    one run (card F4): a run bound to a user resolves to that user, so its MCP
    calls mint from the caller's own ``AuthStore``.

    With no run bound (a direct tool call, a REPL), it falls back to:

    - single-tenant dev  -> ``"local"``, the operator's own machine;
    - otherwise          -> the operator's Clerk id if `ALPHADESK_OPERATOR_EMAIL`
      names a user that has signed in (the same identity adoption moved the
      pre-F3 data onto), else ``"local"``.

    It is **never** "whoever linked first". A non-operator can only ever become
    the resolved identity by being the bound caller of their *own* run — never
    by default — which is the property that matters: a run must not silently
    spend a stranger's grant.

    **`POST /analyze` no longer relies on the fallback.** As of F4 the endpoint
    verifies a real per-user identity, gates on that user's link, and binds it
    here before the graph runs. The fallback survives only for genuinely
    userless callers of `tools/ind_money.py`.
    """
    bound = _run_user.get()
    if bound:
        return bound
    if single_tenant_mode():
        return LOCAL_USER_ID
    from services.adoption import operator_user_id

    return await operator_user_id() or LOCAL_USER_ID


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
_METADATA: Optional[dict] = None


def reset_discovery() -> None:
    """Forget the cached authorization-server metadata. For tests."""
    global _METADATA
    _METADATA = None


async def discover() -> dict:
    """The OAuth authorization-server metadata document, fetched once.

    An unauthenticated GET with no side effect (C2 §Q5), so caching it for the
    process life is free and re-fetching it is harmless.
    """
    global _METADATA
    if _METADATA:
        return _METADATA
    url = _issuer_base() + "/.well-known/oauth-authorization-server"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
    except Exception as exc:  # noqa: BLE001
        raise MCPAuthError(f"OAuth discovery request failed at {url}: {exc}")
    if resp.status_code != 200:
        raise MCPAuthError(f"OAuth discovery failed ({resp.status_code}) at {url}")
    _METADATA = resp.json()
    return _METADATA


async def _register_client(md: dict, redirect_uri: str) -> Tuple[Optional[str], Optional[str]]:
    """Dynamic client registration; returns (client_id, client_secret).

    Does not touch the live token chain — a fresh client is bound to our redirect
    URI and only adopted once login completes, so an in-flight refresh isn't
    broken. C2 verified repeat registration is accepted and returns an
    independent client each time, which is what makes a per-user client viable.
    """
    endpoint = md.get("registration_endpoint")
    if not endpoint:
        raise MCPAuthError("The authorization server advertises no registration_endpoint.")
    body = {
        "client_name": "AlphaDesk",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "scope": _scope(),
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(endpoint, json=body)
    except Exception as exc:  # noqa: BLE001
        raise MCPAuthError(f"Client registration request failed: {exc}")
    if resp.status_code not in (200, 201):
        raise MCPAuthError(f"Client registration failed ({resp.status_code}).")
    reg = resp.json()
    return reg.get("client_id"), reg.get("client_secret")


async def revoke_token(
    token: str, client_id: Optional[str], client_secret: Optional[str]
) -> bool:
    """RFC 7009 revocation of ``token`` at the discovered endpoint.

    Returns True when the server accepted it, False when it advertises no
    revocation endpoint. Raises :class:`MCPAuthError` when the call was made and
    failed — the caller still unlinks, but must be able to say so.

    Scope note (C2 §Q5): this kills **tokens**. The dynamically-registered
    client is not deleted by it, and this server exposes no client-deletion
    path; the client credentials go with the link row locally.
    """
    md = await discover()
    endpoint = md.get("revocation_endpoint")
    if not endpoint:
        return False
    data = {"token": token, "token_type_hint": "refresh_token"}
    if client_id:
        data["client_id"] = client_id
    if client_secret:
        data["client_secret"] = client_secret
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                endpoint, data=data, headers={"Accept": "application/json"}
            )
    except Exception as exc:  # noqa: BLE001
        raise MCPAuthError(f"Token revocation request failed: {exc}")
    # RFC 7009: 200 for success *and* for an already-invalid token.
    if resp.status_code != 200:
        raise MCPAuthError(f"Token revocation failed ({resp.status_code}).")
    return True


# --------------------------------------------------------------------------- #
# Interactive login: state is a row, and the row names its owner
# --------------------------------------------------------------------------- #
#: Single-tenant dev with **no** database configured. The pending row has
#: nowhere to live, so it lives here for the ten minutes it is worth. Never
#: reachable on a deployment: `_pending_in_memory()` requires single-tenant mode
#: AND an unset DATABASE_URL.
_PENDING_DEV: Dict[str, dict] = {}


def _pending_in_memory() -> bool:
    return single_tenant_mode() and not database_configured()


async def begin_login(
    user_id: str, redirect_uri: str, source: str = SOURCE
) -> str:
    """Start an OAuth login **for ``user_id``**; returns the authorization URL.

    Writes the ``state -> user_id`` binding before handing the URL out, so the
    callback can establish the owner from the state alone. Nothing about the
    browser that eventually lands on ``/auth/callback`` is trusted.
    """
    if not user_id:
        raise MCPAuthError("begin_login requires a user_id")
    md = await discover()

    store = AuthStore.for_user(user_id, source)
    await store.ensure_loaded()

    # Reuse the client this user already registered, unless it was bound to a
    # different redirect URI (a deploy that moved the callback), in which case
    # the stored client cannot complete the flow and a new one is registered.
    client_id, client_secret = store._client_id, store._client_secret
    if not client_id or store._redirect_uri != redirect_uri:
        client_id, client_secret = await _register_client(md, redirect_uri)

    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(32)
    token_url = md.get("token_endpoint", _DEFAULT_TOKEN_URL)

    await _store_pending(
        state=state,
        user_id=user_id,
        source=source,
        verifier=verifier,
        redirect_uri=redirect_uri,
        client_id=client_id,
        client_secret=client_secret,
        token_url=token_url,
    )

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": _scope(),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": _RESOURCE,
    }
    return md["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)


async def _store_pending(
    *,
    state: str,
    user_id: str,
    source: str,
    verifier: str,
    redirect_uri: str,
    client_id: Optional[str],
    client_secret: Optional[str],
    token_url: str,
) -> None:
    if _pending_in_memory():
        _PENDING_DEV[state] = {
            "user_id": user_id,
            "source": source,
            "verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "token_url": token_url,
            "created_at": utcnow(),
        }
        return

    async with _session() as session:
        if session is None:
            raise MCPAuthError(
                "Linking a broker account needs a database (DATABASE_URL is unset "
                "on this deployment), because the OAuth state must be bound to "
                "your user id server-side."
            )
        await ensure_user_row(session, user_id)
        try:
            client_secret_enc = encrypt_optional(client_secret)
        except TokenEncryptionError as exc:
            # Same reasoning as `_persist`: refusing in words beats a 500, and
            # beats storing a client secret we could never read back.
            raise MCPAuthError(
                "This server cannot store broker credentials: "
                "TOKEN_ENCRYPTION_KEY is not set or is not a valid Fernet key."
            ) from exc
        session.add(
            OAuthPending(
                state=state,
                user_id=user_id,
                source=source,
                verifier=verifier,
                redirect_uri=redirect_uri,
                client_id=client_id,
                client_secret_enc=client_secret_enc,
                token_url=token_url,
                created_at=utcnow(),
            )
        )
        await session.commit()


async def _consume_pending(state: str) -> dict:
    """Take the pending row for ``state`` — once, and only if it is fresh.

    The read and the delete are **one statement** (``DELETE … RETURNING``). A
    SELECT-then-DELETE would let two callbacks racing on the same state both see
    a row, and the whole point of single-use is that the second one must lose.
    """
    if _pending_in_memory():
        pend = _PENDING_DEV.pop(state, None)
        if pend is None:
            raise OAuthStateError("Unknown or already-used login state.")
        created = pend["created_at"]
    else:
        async with _session() as session:
            if session is None:
                raise MCPAuthError("No database configured; nothing to resolve this login against.")
            result = await session.execute(
                sa_delete(OAuthPending)
                .where(OAuthPending.state == state)
                .returning(
                    OAuthPending.user_id,
                    OAuthPending.source,
                    OAuthPending.verifier,
                    OAuthPending.redirect_uri,
                    OAuthPending.client_id,
                    OAuthPending.client_secret_enc,
                    OAuthPending.token_url,
                    OAuthPending.created_at,
                )
            )
            row = result.first()
            await session.commit()
        if row is None:
            raise OAuthStateError("Unknown or already-used login state.")
        try:
            client_secret = decrypt_optional(row[5])
        except TokenEncryptionError as exc:
            # The key changed between /auth/login and /auth/callback. Rare, but
            # a 500 here would be the least useful possible answer to "I just
            # finished logging in".
            raise MCPAuthError(
                "This login cannot be completed: the server's encryption key "
                "changed while it was in flight. Start the connection again."
            ) from exc
        pend = {
            "user_id": row[0],
            "source": row[1],
            "verifier": row[2],
            "redirect_uri": row[3],
            "client_id": row[4],
            "client_secret": client_secret,
            "token_url": row[6],
        }
        created = row[7]

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if utcnow() - created > timedelta(seconds=STATE_TTL_SECONDS):
        raise OAuthStateError("This login link has expired. Start the connection again.")
    return pend


async def complete_login(code: str, state: str) -> str:
    """Exchange the authorization code for tokens and link **the state's owner**.

    Returns the ``user_id`` the link was written for, so the caller can log it.
    The owner comes from the ``oauth_pending`` row and from nowhere else: the
    request that lands here is a redirect from the broker, and anything it
    carries about identity is attacker-choosable.
    """
    pend = await _consume_pending(state)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pend["redirect_uri"],
        "client_id": pend["client_id"],
        "code_verifier": pend["verifier"],
        "resource": _RESOURCE,
    }
    if pend.get("client_secret"):
        data["client_secret"] = pend["client_secret"]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                pend["token_url"], data=data, headers={"Accept": "application/json"}
            )
    except Exception as exc:  # noqa: BLE001
        raise MCPAuthError(f"Token exchange request failed: {exc}")
    store = AuthStore.for_user(pend["user_id"], pend["source"])
    if resp.status_code != 200:
        if _is_invalid_client(resp):
            # The reused client is dead at the source. Forget it here so the
            # user's *next* press of Connect registers a new one and succeeds,
            # instead of looping through the same rejection.
            await store.ensure_loaded()
            await store.forget_client()
            raise MCPAuthError(
                "IND Money rejected this app's stored registration. It has been "
                "cleared — press Connect again to re-register."
            )
        raise MCPAuthError(f"Token exchange failed ({resp.status_code}).")
    tok = resp.json()

    await store.set_tokens(
        tok.get("access_token"),
        tok.get("refresh_token"),
        tok.get("expires_in"),
        client_id=pend["client_id"],
        client_secret=pend.get("client_secret"),
        scope=tok.get("scope"),
        token_url=pend["token_url"],
        redirect_uri=pend["redirect_uri"],
    )
    log.info("IND Money linked for user %s", pend["user_id"])
    return pend["user_id"]


async def purge_expired_pending() -> int:
    """Delete ``oauth_pending`` rows past their TTL. Returns the row count.

    Housekeeping, not security: expiry is enforced on read, so a leftover row is
    already useless. This is what stops the table growing on abandoned logins.
    """
    cutoff = utcnow() - timedelta(seconds=STATE_TTL_SECONDS)
    async with _session() as session:
        if session is None:
            return 0
        result = await session.execute(
            sa_delete(OAuthPending).where(OAuthPending.created_at < cutoff)
        )
        await session.commit()
        return int(result.rowcount or 0)


__all__ = [
    "DEFAULT_SCOPE",
    "LOCAL_USER_ID",
    "SOURCE",
    "STATE_TTL_SECONDS",
    "AuthStore",
    "MCPAuthError",
    "MCPAuthInvalid",
    "OAuthStateError",
    "ambient_user_id",
    "auth_status",
    "begin_login",
    "bind_run_user",
    "complete_login",
    "database_configured",
    "discover",
    "ensure_user_row",
    "get_access_token",
    "logout",
    "purge_expired_pending",
    "reset_auth_stores",
    "reset_discovery",
    "revoke_token",
    "single_tenant_mode",
    "unbind_run_user",
]
