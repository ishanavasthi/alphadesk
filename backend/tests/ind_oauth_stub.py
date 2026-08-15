"""A stand-in for the IND Money OAuth endpoints, shared by the F3 suites.

Every one of these endpoints has a side effect on a real broker account —
`/register` mints a live OAuth client, `/token` burns a one-use authorization
code, `/revoke` kills a grant a human would have to re-establish by hand — so no
test in this repo is allowed to reach the real ones. Nothing *of ours* is
stubbed: the tokens this hands back go through real Fernet into real Postgres.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

ISSUER = "https://mcp.indmoney.com"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "registration_endpoint": f"{ISSUER}/register",
    "revocation_endpoint": f"{ISSUER}/revoke",
    "scopes_supported": ["portfolio:read", "market:read"],
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "code_challenge_methods_supported": ["S256"],
    "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
}


# --------------------------------------------------------------------------- #
# A stand-in for the broker's OAuth endpoints
# --------------------------------------------------------------------------- #
class FakeBroker:
    """Records every call, and can be told to fail any one of them."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.registrations = 0
        self.token_status = 200
        self.token_body: dict | None = None
        self.revoke_status = 200
        self.access = "acc-1"
        self.refresh = "ref-1"
        self.expires_in = 3600
        self.last_token_form: dict[str, list[str]] = {}
        #: Called (with no arguments) the moment `/revoke` is hit. The hook is
        #: how an ordering test observes *when* revocation happened relative to
        #: our own local delete — a count alone cannot tell the two orders apart.
        self.on_revoke: Callable[[], None] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = urlsplit(str(request.url)).path
        self.calls.append(path)
        if path.startswith("/.well-known/"):
            return httpx.Response(200, json=DISCOVERY)
        if path == "/register":
            self.registrations += 1
            return httpx.Response(
                201,
                json={
                    "client_id": f"cli-{self.registrations}",
                    "client_secret": f"sec-{self.registrations}",
                    "scope": "portfolio:read market:read",
                },
            )
        if path == "/token":
            self.last_token_form = parse_qs(request.content.decode())
            if self.token_status != 200:
                if self.token_body is not None:
                    return httpx.Response(self.token_status, json=self.token_body)
                return httpx.Response(self.token_status, text="nope")
            return httpx.Response(
                200,
                json={
                    "access_token": self.access,
                    "refresh_token": self.refresh,
                    "expires_in": self.expires_in,
                    "scope": "portfolio:read market:read",
                },
            )
        if path == "/revoke":
            if self.on_revoke is not None:
                self.on_revoke()
            return httpx.Response(self.revoke_status, text="")
        return httpx.Response(404, text="unmapped")


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeBroker]:
    """Route every httpx call made during the test into :class:`FakeBroker`."""
    fake = FakeBroker()
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    yield fake


__all__ = ["DISCOVERY", "ISSUER", "FakeBroker", "broker"]
