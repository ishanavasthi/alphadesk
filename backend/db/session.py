"""Async engine + FastAPI session dependency.

Not wired into any endpoint as of F1 — `api.main` does not import this module.
The first consumers are F3 (per-user broker links) and M1 (portfolio reads).

`DATABASE_URL` is normalised to the asyncpg driver, so all of these work and
mean the same thing:

    postgresql://user:pw@host/db
    postgres://user:pw@host/db          (the form Neon/Heroku hand out)
    postgresql+asyncpg://user:pw@host/db

**Including the query string a managed provider actually hands you.** A real
Neon URL ends in `?sslmode=require&channel_binding=require`; SQLAlchemy's
asyncpg dialect forwards every query parameter straight into
`asyncpg.connect()`, which knows neither keyword and raises `TypeError` on the
first connection. `normalize_url()` therefore translates `sslmode` → asyncpg's
`ssl` and drops `channel_binding` (asyncpg negotiates channel binding itself)
when the target driver is asyncpg. `sync_url()` leaves the query alone, because
libpq-based drivers do understand `sslmode`.

Alembic normalises the same way (`alembic/env.py`), so one env var drives both
the app and migrations. Nothing here assumes a specific Postgres host — local
Docker, Neon, or anything else with a Postgres URL works.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

ENV_VAR = "DATABASE_URL"

ASYNC_DRIVER = "postgresql+asyncpg"
SYNC_DRIVER = "postgresql"

_MISSING_URL_MSG = (
    f"{ENV_VAR} is not set. Point it at a Postgres instance, e.g. "
    "postgresql+asyncpg://postgres:test@localhost:5433/alphadesk "
    "(see docs/TESTING/F1.md for a one-line local Docker Postgres)."
)


def _split_scheme(url: str) -> tuple[str, str]:
    """Return `(dialect, driver)` from a SQLAlchemy URL scheme."""
    scheme = urlsplit(url).scheme
    dialect, _, driver = scheme.partition("+")
    return dialect, driver


#: libpq query parameters asyncpg does not accept as `connect()` keywords.
#: SQLAlchemy's asyncpg dialect splats `url.query` into `asyncpg.connect()`, so
#: anything left here becomes a `TypeError` on the first connection.
#: `sslmode` has a direct equivalent (`ssl`); `channel_binding` has none —
#: asyncpg negotiates SCRAM channel binding itself, so dropping it is safe.
_LIBPQ_ONLY_PARAMS = ("channel_binding",)


def _asyncpg_query(query: str) -> str:
    """Rewrite a libpq query string into one `asyncpg.connect()` accepts."""
    params = parse_qsl(query, keep_blank_values=True)
    if not params:
        return query

    has_ssl = any(key == "ssl" for key, _ in params)
    out: list[tuple[str, str]] = []
    for key, value in params:
        if key in _LIBPQ_ONLY_PARAMS:
            continue
        if key == "sslmode":
            # asyncpg's `ssl` takes the same vocabulary (disable/allow/prefer/
            # require/verify-ca/verify-full). An explicit `ssl` already in the
            # URL wins.
            if has_ssl:
                continue
            key = "ssl"
        out.append((key, value))
    return urlencode(out)


def normalize_url(url: str, *, driver: str = ASYNC_DRIVER) -> str:
    """Rewrite a Postgres URL's scheme to `driver`, fixing driver-specific args.

    `postgres://` (the alias Neon/Heroku emit) is accepted as `postgresql`.
    When `driver` is asyncpg the query string is translated as well, so a
    provider URL can be pasted verbatim:

        postgresql://u:p@ep.neon.tech/db?sslmode=require&channel_binding=require
        -> postgresql+asyncpg://u:p@ep.neon.tech/db?ssl=require

    A non-Postgres URL — e.g. `sqlite+aiosqlite://` — is returned untouched so
    the helper stays usable in throwaway contexts.
    """
    dialect, _ = _split_scheme(url)
    if dialect not in ("postgres", "postgresql"):
        return url
    parts = urlsplit(url)
    if driver == ASYNC_DRIVER:
        parts = parts._replace(query=_asyncpg_query(parts.query))
    return urlunsplit(parts._replace(scheme=driver))


def async_url(url: str) -> str:
    """The asyncpg form of `url` — what the app engine uses."""
    return normalize_url(url, driver=ASYNC_DRIVER)


def sync_url(url: str) -> str:
    """The driverless (`postgresql://`) form — for tools that want a sync DBAPI."""
    return normalize_url(url, driver=SYNC_DRIVER)


def get_database_url() -> str:
    """The configured `DATABASE_URL`, normalised for asyncpg.

    Read lazily so importing `db.session` never fails on an unconfigured box.
    """
    raw = os.getenv(ENV_VAR)
    if not raw:
        raise RuntimeError(_MISSING_URL_MSG)
    return async_url(raw)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Process-wide async engine, created on first use."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_database_url(),
            echo=False,
            pool_pre_ping=True,  # serverless Postgres drops idle connections
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Process-wide `AsyncSession` factory bound to `get_engine()`."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an `AsyncSession`.

        @app.get("/whatever")
        async def handler(session: AsyncSession = Depends(async_session)):
            ...

    The session is closed on the way out; committing is the caller's job.
    """
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Drop the engine + its pool. For app shutdown and test teardown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
