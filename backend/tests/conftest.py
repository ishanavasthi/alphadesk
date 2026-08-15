"""Shared pytest fixtures.

Database tests run against a **real Postgres** — the cascade behaviour and the
`timestamptz` columns this card is about are exactly the things SQLite would
lie about. The default target is the local Docker container from
`docs/TESTING/F1.md`:

    docker run --rm -d --name alphadesk-f1-pg \
      -e POSTGRES_PASSWORD=test -e POSTGRES_DB=alphadesk \
      -p 5433:5432 postgres:16

Point `TEST_DATABASE_URL` (or `DATABASE_URL`) somewhere else to override. The
fixture creates a **separate `<db>_test` database** on the same server so a dev
DB is never touched, and builds its schema by running `alembic upgrade head` —
the tests therefore exercise the migration, not a parallel `create_all()`.

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


def _base_url() -> str:
    raw = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_TEST_DB_URL
    return async_url(raw)


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def _database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/") or "postgres"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_database_url() -> str:
    """URL of a freshly-migrated `<db>_test` database, or skip if no Postgres."""
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


@pytest_asyncio.fixture
async def db_session(test_database_url: str):
    """A clean `AsyncSession`; all three tables are truncated afterwards."""
    engine = create_async_engine(test_database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
        async with engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(
                text("TRUNCATE users, broker_links, oauth_pending RESTART IDENTITY CASCADE")
            )
    finally:
        await engine.dispose()
