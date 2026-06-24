"""OAuth token management for the IND Money MCP server.

The IND Money MCP authenticates with OAuth 2.0; access tokens expire (~1h) and
must be refreshed with the stored refresh token. This module provides
``get_access_token()`` which returns a valid bearer token, refreshing on demand.

Credential sources, in priority order:
  1. ``IND_MONEY_MCP_TOKEN`` env var — a static bearer token (escape hatch; no refresh).
  2. ``backend/.ind_money_token.json`` cache (written here after each refresh).
  3. ``IND_MONEY_OAUTH_*`` env vars (CLIENT_ID / REFRESH_TOKEN / TOKEN_URL / SCOPE).
  4. The Claude Code credential store (~/.claude/.credentials.json, mcpOAuth) —
     reuses an existing `indmoney` login so the backend works without extra setup.

Refresh tokens rotate, so each refresh is persisted back to the cache file.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

_CACHE_FILE = Path(__file__).resolve().parents[1] / ".ind_money_token.json"
_CLAUDE_CREDS = Path.home() / ".claude" / ".credentials.json"
_DEFAULT_TOKEN_URL = "https://mcp.indmoney.com/token"
_CLAUDE_PREFIX = "indmoney"


class MCPAuthError(Exception):
    """Raised when a valid IND Money access token cannot be obtained."""


class _Auth:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._loaded = False
        self._access: Optional[str] = None
        self._refresh: Optional[str] = None
        self._expires_at: float = 0.0  # epoch seconds
        self._client_id: Optional[str] = None
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
                self._token_url = d.get("token_url") or self._token_url
                self._scope = d.get("scope")
            except Exception:  # noqa: BLE001 - corrupt cache is non-fatal
                pass

        self._token_url = os.environ.get("IND_MONEY_OAUTH_TOKEN_URL", self._token_url)
        self._scope = self._scope or os.environ.get("IND_MONEY_OAUTH_SCOPE")
        self._client_id = self._client_id or os.environ.get("IND_MONEY_OAUTH_CLIENT_ID")
        self._refresh = self._refresh or os.environ.get("IND_MONEY_OAUTH_REFRESH_TOKEN")

        if not self._refresh and _CLAUDE_CREDS.exists():
            self._seed_from_claude()

        self._loaded = True

    def _seed_from_claude(self) -> None:
        """Bootstrap from an existing Claude Code `indmoney` OAuth login."""
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
                    # Claude stores ms epoch; normalize to seconds.
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
                        "token_url": self._token_url,
                        "scope": self._scope,
                    }
                ),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001 - cache write failure is non-fatal
            pass

    async def get_token(self) -> str:
        if self._static:
            return self._static
        async with self._lock:
            if not self._loaded:
                self._load()
            if self._static:
                return self._static
            if self._access and (self._expires_at - time.time()) > 60:
                return self._access
            return await self._refresh_token()

    async def _refresh_token(self) -> str:
        if not self._refresh or not self._client_id:
            raise MCPAuthError(
                "No IND Money OAuth credentials. Authenticate the 'indmoney' MCP in "
                "Claude Code, or set IND_MONEY_OAUTH_CLIENT_ID / "
                "IND_MONEY_OAUTH_REFRESH_TOKEN (or IND_MONEY_MCP_TOKEN)."
            )
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh,
            "client_id": self._client_id,
        }
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
                "Re-authenticate the 'indmoney' MCP in Claude Code."
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
