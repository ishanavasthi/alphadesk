"""`Server-Timing` instrumentation (issue #72, phase 0).

Every number in the latency debate must come from measurement, so the portfolio
routes report theirs: a `total` span from the middleware on every response, plus
`db` / `src` / `cache` spans the portfolio routes record around their two
phases (own database vs rate-limited source vs read-through cache). Read them
in devtools or with `curl -D-`; the frontend's own sequencing marks live in
`PortfolioProvider` (`performance.mark`, dev console only).

Three rules keep this honest and cheap:

1. **Never load-bearing.** A route that records no span still gets `total`; a
   non-HTTP scope passes through untouched. The header is absent only when
   there is nothing to say, never wrong.
2. **No PII in span names.** Names are a closed set (`total`, `db`, `src`,
   `cache`) — never a user id, asset type, or query string.
3. **Pure ASGI, no `BaseHTTPMiddleware`.** The dashboard streams SSE
   (`/analyze`, `/portfolio/overview`); base-HTTP middleware is known to
   interfere with streaming responses. This middleware only appends a header
   on `http.response.start` and never touches the body.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Iterator

from fastapi import Request

#: The only span names this module ever emits. See rule 2 above.
TOTAL = "total"
DB = "db"
SRC = "src"
CACHE = "cache"

#: ASGI scope key carrying the per-request span list. Stored on the scope
#: directly (not `request.state`) so the middleware and the `span` helper share
#: exactly one dict without depending on Starlette's `State` plumbing.
_SCOPE_KEY = "alphadesk.server_timing_spans"


@contextmanager
def span(request: Request | None, name: str) -> Iterator[None]:
    """Time one phase of a route into the response's `Server-Timing` header."""
    start = time.perf_counter()
    try:
        yield
    finally:
        if request is None:
            return
        request.scope.setdefault(_SCOPE_KEY, []).append(
            (name, (time.perf_counter() - start) * 1000.0)
        )


class ServerTimingMiddleware:
    """Append `Server-Timing: total;dur=…[, db;…, src;…, cache;…]`."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()

        async def send_with_timing(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                spans: list[tuple[str, float]] = [
                    (TOTAL, (time.perf_counter() - start) * 1000.0)
                ]
                spans.extend(scope.get(_SCOPE_KEY, []))
                headers = list(message.setdefault("headers", []))
                headers.append(
                    (
                        b"server-timing",
                        ", ".join(
                            f"{name};dur={dur:.1f}" for name, dur in spans
                        ).encode("latin-1"),
                    )
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_timing)


__all__ = ["CACHE", "DB", "SRC", "TOTAL", "ServerTimingMiddleware", "span"]
