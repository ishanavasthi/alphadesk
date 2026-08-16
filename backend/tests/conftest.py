"""Shared pytest fixtures.

Database tests run against a **real Postgres** — the cascade behaviour and the
`timestamptz` columns this card is about are exactly the things SQLite would
lie about. The default target is the local Docker container from
`docs/TESTING/F1.md`:

    docker run --rm -d --name alphadesk-f1-pg \
      -e POSTGRES_PASSWORD=test -e POSTGRES_DB=alphadesk \
      -p 5433:5432 postgres:16

Point `TEST_DATABASE_URL` somewhere else to override. The fixture creates a
**separate `<db>_test` database** on the same server so a dev DB is never
touched, and builds its schema by running `alembic upgrade head` — the tests
therefore exercise the migration, not a parallel `create_all()`.

**Safety guard:** the fixture runs `DROP DATABASE ... WITH (FORCE)`, so an
inherited `DATABASE_URL` is only honoured when it points at loopback. Anything
else must be named explicitly in `TEST_DATABASE_URL` — see
`resolve_test_database_url()`.

If no Postgres is reachable, the DB tests skip with a message naming the URL
tried. Everything else (crypto, tracing) runs with no services at all.
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.session import async_url

DEFAULT_TEST_DB_URL = "postgresql+asyncpg://postgres:test@localhost:5433/alphadesk"

#: Fixed key so an encrypted value is reproducible within a run. Test-only —
#: real keys live in backend/.env, which is gitignored.
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Every test gets a valid `TOKEN_ENCRYPTION_KEY` unless it clears it."""
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    return TEST_ENCRYPTION_KEY


@pytest.fixture(autouse=True)
def _isolate_token_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: "os.PathLike[str]"
) -> None:
    """No test may read or write `backend/.ind_money_token.json`.

    `_persist_file()` mirrors credentials to that path whenever
    `_is_local_dev()` holds — `ALPHADESK_SINGLE_TENANT=1` and user `local`.
    Both are true inside the suite on an operator's machine, because
    `api.main` calls `load_dotenv()` at import and a real `backend/.env` sets
    the flag. Three tests remembered to redirect `_CACHE_FILE` to a `tmp_path`;
    any test that reached a persist without doing so overwrote the operator's
    live credential with the OAuth stub's fixtures, and the next real login was
    rejected with `Client ID 'cli-1' not found`.

    Isolation belongs here rather than in each test for the same reason
    `_auth_html` escapes centrally: a rule enforced per-call site is a rule
    that will eventually be forgotten. `tests/test_token_cache_isolation.py`
    fails if this fixture is removed.
    """
    from tools import ind_money_auth

    monkeypatch.setattr(
        ind_money_auth, "_CACHE_FILE", tmp_path / ".ind_money_token.json"
    )


@pytest.fixture(autouse=True)
def _reset_langsmith_env_cache():
    """Clear langsmith's `get_env_var` LRU cache around every test.

    `langsmith.utils.get_env_var` is `functools.lru_cache`d, so the very first
    read of the tracing env vars is frozen for the rest of the process. Before
    card A1 nothing actually *ran* a LangGraph in the suite, so the cache was
    only ever populated inside `test_portfolio_config`'s own env fixture and the
    fragility was invisible. A1 runs the portfolio graph in tests: the graph
    reads the tracing state (with tracing off), which would otherwise freeze
    "disabled" and make `test_portfolio_config`'s control case ("the env var
    really would enable tracing") fail depending on file order. Clearing the
    cache before and after each test makes every test read the env it actually
    set, restoring order-independence.
    """
    try:
        from langsmith.utils import get_env_var
    except Exception:  # noqa: BLE001 - langsmith always present, but never fatal
        yield
        return
    get_env_var.cache_clear()
    yield
    get_env_var.cache_clear()


#: Hosts the suite is willing to run `DROP DATABASE` against without being told
#: to explicitly. Everything else is assumed to be someone's real server.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", ""})


class UnsafeTestDatabase(RuntimeError):
    """Raised when the suite would drop a database on a non-loopback host."""


def resolve_test_database_url(
    test_database_url: str | None,
    database_url: str | None,
    default: str = DEFAULT_TEST_DB_URL,
) -> str:
    """Pick the server the suite may create and drop `<db>_test` on.

    The fixture below runs `DROP DATABASE ... WITH (FORCE)`. That is fine
    against a throwaway local container and catastrophic against a staging or
    production Postgres — so inheriting `DATABASE_URL` from the shell is only
    allowed when it points at loopback. A remote target must be named
    explicitly in `TEST_DATABASE_URL`, which is a deliberate act rather than a
    leftover export.

    `TEST_DATABASE_URL` itself is trusted whatever the host: naming it *is* the
    confirmation.
    """
    if test_database_url:
        return async_url(test_database_url)

    if database_url:
        host = (urlsplit(async_url(database_url)).hostname or "").lower()
        if host not in LOOPBACK_HOSTS:
            raise UnsafeTestDatabase(
                f"Refusing to run the test suite against DATABASE_URL (host "
                f"{host!r}): the suite creates and DROPs a <db>_test database, "
                "and an inherited DATABASE_URL is usually a leftover export "
                "pointing at a real server. Set TEST_DATABASE_URL explicitly if "
                "you really mean this host, or unset DATABASE_URL to use the "
                f"local default ({default})."
            )
        return async_url(database_url)

    return async_url(default)


def _base_url() -> str:
    return resolve_test_database_url(
        os.getenv("TEST_DATABASE_URL"), os.getenv("DATABASE_URL")
    )


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def _database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/") or "postgres"


#: Process-level guard so the destructive DROP+CREATE+migrate below runs EXACTLY
#: ONCE, even if the session-scoped fixture is re-instantiated mid-run. It should
#: not be — but pytest-asyncio can tear down and re-setup a session-scoped async
#: fixture when the session event loop it is bound to is finalized, which
#: pytest-randomly's reordering makes happen. A second `DROP DATABASE ... WITH
#: (FORCE)` mid-suite force-closes live pooled connections and drops the database
#: out from under whatever test is tearing down at that instant — the
#: `ConnectionDoesNotExist` / "database ... does not exist" / "relation ... does
#: not exist" cascade that made the suite order-fragile. Once the throwaway DB
#: exists and is migrated it stays good (every test truncates between runs), so a
#: re-setup must be a harmless no-op that returns the same URL, never a second
#: teardown-of-everything.
_TEST_DB_URL: str | None = None


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_database_url() -> str:
    """URL of a `<db>_test` database, migrated **once per process**, or skip.

    The drop/create/migrate is guarded by :data:`_TEST_DB_URL` so it happens a
    single time regardless of how many times this session fixture is set up (see
    that note): re-running the `WITH (FORCE)` drop mid-suite is what made the
    suite flaky under `pytest-randomly`.
    """
    global _TEST_DB_URL
    if _TEST_DB_URL is not None:
        return _TEST_DB_URL

    base = _base_url()
    admin_url = _with_database(base, "postgres")
    test_db = f"{_database_name(base)}_test"
    test_url = _with_database(base, test_db)

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            from sqlalchemy import text

            await conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    except Exception as exc:  # noqa: BLE001 - any connection failure means "no DB"
        pytest.skip(
            f"No Postgres reachable at {admin_url} ({type(exc).__name__}). "
            "Start it with the docker one-liner in docs/TESTING/F1.md, or set "
            "TEST_DATABASE_URL."
        )
    finally:
        await admin_engine.dispose()

    # In a worker thread: alembic/env.py drives its own asyncio.run(), which
    # cannot be nested inside this fixture's running event loop.
    await asyncio.to_thread(_alembic_upgrade, test_url)
    _TEST_DB_URL = test_url
    return test_url


def _alembic_upgrade(url: str) -> None:
    """`alembic upgrade head` against `url`, driven from backend/alembic.ini."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.attributes["db_url"] = url  # read by alembic/env.py:get_url()
    command.upgrade(cfg, "head")


#: Every table the suite writes to, truncated between tests. `users` cascades to
#: the rest, but they are named anyway so that adding a table without adding it
#: here is a visible omission rather than a silent one.
_ALL_TABLES = (
    "users",
    "broker_links",
    "oauth_pending",
    "snapshot_days",
    "snapshot_holdings",
    "snapshot_raw",
    "watchlist",
)


@pytest_asyncio.fixture
async def db_env(test_database_url: str, monkeypatch: pytest.MonkeyPatch):
    """Point the **application's** engine at the test database (card F3).

    `db_session` hands a test its own session. That is not enough for code whose
    whole point is that it opens its own — `AuthStore` reads and writes a
    `broker_links` row from wherever the request happens to be, so it goes
    through `db.session.get_sessionmaker()`. This fixture makes that factory
    resolve to the same throwaway `<db>_test` database, disposes the engine on
    both sides of the test so no pooled connection outlives it, and truncates
    afterwards.

    Yields a sessionmaker for the test's own assertions about raw rows.
    """
    from db import session as db_session_module

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    await db_session_module.dispose_engine()

    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await db_session_module.dispose_engine()
        async with engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(
                text(f"TRUNCATE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE")
            )
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_database_url: str):
    """A clean `AsyncSession`; every table is truncated afterwards."""
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
        async with engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(
                text(
                    f"TRUNCATE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()
