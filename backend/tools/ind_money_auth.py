"""OAuth for the IND Money MCP server: token refresh + interactive login.

Two parts:

1. Token lifecycle (``get_access_token``): returns a valid bearer token, refreshing
   with the stored refresh token when the access token expires, and persisting the
   rotated tokens to ``backend/.ind_money_token.json``.

2. Interactive login (``begin_login`` / ``complete_login``): an OAuth
   authorization-code + PKCE flow with dynamic client registration, so the backend
   can authenticate itself (e.g. from a "Connect IND Money" button) without piggy-
   backing the Claude Code login.

Credential sources for the token lifecycle, in priority order:
  1. ``IND_MONEY_MCP_TOKEN`` env — static bearer (no refresh).
  2. ``backend/.ind_money_token.json`` cache (written after each refresh / login).
  3. ``IND_MONEY_OAUTH_*`` env (CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN / TOKEN_URL / SCOPE).
  4. The Claude Code credential store (~/.claude/.credentials.json, mcpOAuth indmoney).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path
from typing import Dict, Optional

import httpx

_CACHE_FILE = Path(__file__).resolve().parents[1] / ".ind_money_token.json"
_CLAUDE_CREDS = Path.home() / ".claude" / ".credentials.json"
_DEFAULT_TOKEN_URL = "https://mcp.indmoney.com/token"
_CLAUDE_PREFIX = "indmoney"
_RESOURCE = "https://mcp.indmoney.com/"
_SCOPE = os.environ.get("IND_MONEY_OAUTH_SCOPE", "portfolio:read")


class MCPAuthError(Exception):
    """Raised when a valid IND Money access token cannot be obtained."""


def _issuer_base() -> str:
    url = os.environ.get("IND_MONEY_MCP_URL") or "https://mcp.indmoney.com/mcp"
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class _Auth:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._loaded = False
        self._access: Optional[str] = None
        self._refresh: Optional[str] = None
        self._expires_at: float = 0.0
        self._client_id: Optional[str] = None
        self._client_secret: Optional[str] = None
        self._token_url: str = _DEFAULT_TOKEN_URL
        self._scope: Optional[str] = None
        self._static: Optional[str] = None

    def _load(self) -> None:
        self._static = os.environ.get("IND_MONEY_MCP_TOKEN") or None

        if _CACHE_FILE.exists():
            try:
                d = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                self._access = d.get("access_token")
                self._refresh = d.get("refresh_token")
                self._expires_at = d.get("expires_at", 0.0)
                self._client_id = d.get("client_id")
                self._client_secret = d.get("client_secret")
                self._token_url = d.get("token_url") or self._token_url
                self._scope = d.get("scope")
            except Exception:  # noqa: BLE001
                pass

        self._token_url = os.environ.get("IND_MONEY_OAUTH_TOKEN_URL", self._token_url)
        self._scope = self._scope or os.environ.get("IND_MONEY_OAUTH_SCOPE")
        self._client_id = self._client_id or os.environ.get("IND_MONEY_OAUTH_CLIENT_ID")
        self._client_secret = self._client_secret or os.environ.get("IND_MONEY_OAUTH_CLIENT_SECRET")
        self._refresh = self._refresh or os.environ.get("IND_MONEY_OAUTH_REFRESH_TOKEN")

        if not self._refresh and _CLAUDE_CREDS.exists():
            self._seed_from_claude()

        self._loaded = True

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

    def _persist(self) -> None:
        try:
            _CACHE_FILE.write_text(
                json.dumps(
                    {
                        "access_token": self._access,
                        "refresh_token": self._refresh,
                        "expires_at": self._expires_at,
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "token_url": self._token_url,
                        "scope": self._scope,
                    }
                ),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()

    def set_tokens(
        self,
        access: Optional[str],
        refresh: Optional[str],
        expires_in: Optional[int],
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        token_url: Optional[str] = None,
    ) -> None:
        self.ensure_loaded()
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
        self._static = None  # real OAuth tokens now own the chain
        self._persist()

    def status(self) -> Dict[str, object]:
        self.ensure_loaded()
        if self._static:
            return {"authenticated": True, "source": "static", "expires_at": None}
        now = time.time()
        # Authenticated if we have a live access token or a refresh token to mint one.
        authed = bool((self._access and self._expires_at - now > 60) or self._refresh)
        return {
            "authenticated": authed,
            "source": "oauth" if authed else None,
            "expires_at": self._expires_at or None,
            "expires_in_sec": int(self._expires_at - now) if self._expires_at else None,
        }

    async def get_token(self) -> str:
        if self._static:
            return self._static
        async with self._lock:
            self.ensure_loaded()
            if self._static:
                return self._static
            if self._access and (self._expires_at - time.time()) > 60:
                return self._access
            return await self._refresh_token()

    async def _refresh_token(self) -> str:
        if not self._refresh or not self._client_id:
            raise MCPAuthError(
                "Not authenticated with IND Money. Use the Connect button, authenticate "
                "the 'indmoney' MCP in Claude Code, or set IND_MONEY_OAUTH_* env vars."
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
            raise MCPAuthError(
                f"IND Money token refresh failed ({resp.status_code}): {resp.text[:200]}. "
                "Re-connect via the Connect button."
            )
        tok = resp.json()
        self._access = tok.get("access_token")
        if tok.get("refresh_token"):
            self._refresh = tok["refresh_token"]
        self._expires_at = time.time() + int(tok.get("expires_in", 3600))
        self._persist()
        if not self._access:
            raise MCPAuthError("IND Money token endpoint returned no access_token.")
        return self._access


_auth = _Auth()


async def get_access_token() -> str:
    """Return a valid IND Money bearer token, refreshing if needed."""
    return await _auth.get_token()


async def auth_status() -> Dict[str, object]:
    """Return whether the backend is authenticated with IND Money."""
    return _auth.status()


# --------------------------------------------------------------------------- #
# Interactive login (authorization code + PKCE + dynamic client registration)
# --------------------------------------------------------------------------- #
_METADATA: Optional[dict] = None
_PENDING: Dict[str, dict] = {}  # state -> {verifier, redirect_uri, client_id, client_secret, token_url}


async def _discover() -> dict:
    global _METADATA
    if _METADATA:
        return _METADATA
    url = _issuer_base() + "/.well-known/oauth-authorization-server"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise MCPAuthError(f"OAuth discovery failed ({resp.status_code}) at {url}")
    _METADATA = resp.json()
    return _METADATA


async def _register_client(md: dict, redirect_uri: str) -> tuple:
    """Dynamic client registration; returns (client_id, client_secret).

    Does not touch the live token chain — a fresh client is bound to our redirect
    URI and only adopted once login completes, so an in-flight refresh isn't broken.
    """
    body = {
        "client_name": "AlphaDesk",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "scope": _SCOPE,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(md["registration_endpoint"], json=body)
    if resp.status_code not in (200, 201):
        raise MCPAuthError(f"Client registration failed ({resp.status_code}): {resp.text[:200]}")
    reg = resp.json()
    return reg.get("client_id"), reg.get("client_secret")


async def begin_login(redirect_uri: str) -> str:
    """Start an OAuth login; returns the authorization URL to open in a browser."""
    md = await _discover()
    # Always register a client bound to our redirect_uri (don't reuse a cached
    # client registered for a different redirect).
    client_id, client_secret = await _register_client(md, redirect_uri)

    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(16)
    _PENDING[state] = {
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "token_url": md.get("token_endpoint", _DEFAULT_TOKEN_URL),
    }
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": _SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": _RESOURCE,
    }
    return md["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)


async def complete_login(code: str, state: str) -> None:
    """Exchange the authorization code for tokens and store them."""
    pend = _PENDING.pop(state, None)
    if not pend:
        raise MCPAuthError("Unknown or expired login state.")
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
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            pend["token_url"], data=data, headers={"Accept": "application/json"}
        )
    if resp.status_code != 200:
        raise MCPAuthError(f"Token exchange failed ({resp.status_code}): {resp.text[:200]}")
    tok = resp.json()
    _auth.set_tokens(
        tok.get("access_token"),
        tok.get("refresh_token"),
        tok.get("expires_in"),
        client_id=pend["client_id"],
        client_secret=pend.get("client_secret"),
        scope=tok.get("scope"),
        token_url=pend["token_url"],
    )
