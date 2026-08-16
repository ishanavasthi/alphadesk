"""Per-user / per-IP request rate limits on the expensive surfaces (card L1).

Three endpoints cost real money or real work on every call and are the ones a
runaway client (or an attacker) would point at:

- ``POST /analyze`` — a full Groq research run;
- ``POST /portfolio/overview`` — an OpenAI multi-agent narrative;
- ``POST /auth/login`` — an OAuth round-trip and a dynamic client registration.

This middleware caps them. It is a **request-rate** limit — "how many calls in a
window" — and it answers **429** past the ceiling, distinct from the overview's
*spend* cap (`agents.portfolio.spend`), which counts LLM generations per day and
**degrades** rather than erroring because A1 requires the dashboard to render
completely when the model is unavailable. Both exist; they guard different
things.

Two ceilings, both fixed-window and both configurable from the environment on
every request (so an operator can retune without a restart):

- a **per-caller** cap — keyed by the bearer token when one is present (a proxy
  for the user) and by client IP otherwise, so one noisy caller cannot exhaust
  the budget for everyone;
- a **global** cap across all callers, the backstop against a distributed flood.

Defaults are set high enough that ordinary use — and the test suite — never trips
them; the dedicated test sets them low. State is in-memory per process, matching
the rest of the Lab/overview state (CLAUDE.md): appropriate for "stop a loop",
not for accounting across replicas.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

#: The surfaces this middleware guards, matched as exact path prefixes.
GUARDED_PATHS: tuple[str, ...] = ("/analyze", "/portfolio/overview", "/auth/login")

_WINDOW_ENV = "RATE_LIMIT_WINDOW_SECONDS"
_PER_CALLER_ENV = "RATE_LIMIT_PER_CALLER_MAX"
_GLOBAL_ENV = "RATE_LIMIT_GLOBAL_MAX"
_ENABLED_ENV = "RATE_LIMIT_ENABLED"

#: Deliberately generous. The point is to stop a loop or a flood, not to police
#: honest use — a human clicking Connect or refreshing an overview never gets
#: near these. The rate-limit test overrides them to small values.
_DEFAULT_WINDOW = 60
_DEFAULT_PER_CALLER = 60
_DEFAULT_GLOBAL = 600


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _enabled() -> bool:
    return (os.environ.get(_ENABLED_ENV) or "1").strip().lower() not in ("0", "false", "no")


class _FixedWindow:
    """Counts events per key inside a rolling fixed window, plus a global total.

    A single window boundary for the whole limiter: when it rolls, every count
    resets at once. That is coarser than a sliding window and exactly right for a
    loop-stopper — cheap, and its worst case (a burst straddling a boundary) is a
    brief over-allowance, never an under-count that would let a flood through.
    """

    def __init__(self) -> None:
        self._window_id: Optional[int] = None
        self._per_key: dict[str, int] = {}
        self._global = 0

    def _roll(self, window_id: int) -> None:
        if self._window_id != window_id:
            self._window_id = window_id
            self._per_key = {}
            self._global = 0

    def hit(
        self, key: str, *, per_caller_max: int, global_max: int, window: int, now: float
    ) -> Optional[int]:
        """Record one request. Returns ``None`` if allowed, else ``retry_after``.

        The check and the increment are one synchronous span with no ``await``
        between them, so on a single event loop no two requests can both pass a
        boundary they should not.
        """
        window_id = int(now // window)
        self._roll(window_id)
        retry_after = int((window_id + 1) * window - now) or 1
        if self._global >= global_max:
            return retry_after
        if self._per_key.get(key, 0) >= per_caller_max:
            return retry_after
        self._global += 1
        self._per_key[key] = self._per_key.get(key, 0) + 1
        return None

    def reset(self) -> None:
        self._window_id = None
        self._per_key = {}
        self._global = 0


_WINDOW = _FixedWindow()


def reset_rate_limits() -> None:
    """Clear all counters. For tests and between deployments."""
    _WINDOW.reset()


def _caller_key(scope: Scope) -> str:
    """A stable key for the caller: the bearer token if present, else client IP.

    The token is hashed, never stored raw — this dict is long-lived and must not
    become a pile of credentials. Hashing also collapses the ~1-minute rotation
    of a Clerk session token into per-request noise, but that is acceptable for a
    coarse loop-stopper and the global cap is the real backstop.
    """
    for name, value in scope.get("headers", []):
        if name == b"authorization" and value:
            digest = hashlib.sha256(value).hexdigest()[:16]
            return f"tok:{digest}"
    client = scope.get("client")
    host = client[0] if client else "unknown"
    return f"ip:{host}"


class RateLimitMiddleware:
    """ASGI middleware enforcing :data:`GUARDED_PATHS`' request-rate ceilings."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _enabled():
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not any(path.startswith(p) for p in GUARDED_PATHS):
            await self.app(scope, receive, send)
            return

        window = _int_env(_WINDOW_ENV, _DEFAULT_WINDOW)
        per_caller = _int_env(_PER_CALLER_ENV, _DEFAULT_PER_CALLER)
        global_max = _int_env(_GLOBAL_ENV, _DEFAULT_GLOBAL)
        key = _caller_key(scope)
        retry_after = _WINDOW.hit(
            key,
            per_caller_max=per_caller,
            global_max=global_max,
            window=window,
            now=time.time(),
        )
        if retry_after is not None:
            response = JSONResponse(
                {
                    "detail": {
                        "code": "rate_limited",
                        "message": (
                            "Too many requests to this endpoint; slow down and "
                            "retry shortly."
                        ),
                        "retry_after": retry_after,
                    }
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


__all__ = ["GUARDED_PATHS", "RateLimitMiddleware", "reset_rate_limits"]
