"""Alembic environment — async, driven by DATABASE_URL.

**Decision: migrations run on the same async engine as the app** (asyncpg via
`connection.run_sync`). The alternative was a second, sync driver (psycopg2)
just for Alembic; that would mean a second Postgres driver in the runtime
image, a second URL form to keep in sync, and a second thing to get wrong.
Instead `db.session.async_url()` normalises whatever `DATABASE_URL` holds —
`postgres://`, `postgresql://` or `postgresql+asyncpg://` — to the asyncpg
form, so operators can paste a provider URL verbatim.

Run from `backend/`:  `alembic upgrade head`
Override the target:  `alembic -x db_url=postgresql+asyncpg://... upgrade head`
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# `prepend_sys_path = .` in alembic.ini puts backend/ on sys.path, so these
# import exactly as they do under uvicorn — no `backend.` prefix.
from db import session as db_session  # noqa: E402
from db.models import SQLModel  # noqa: E402
import db.models  # noqa: E402,F401  (import registers all three tables)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _load_dotenv() -> None:
    """Load backend/.env if python-dotenv is available, so `alembic` needs no
    extra shell setup. Never overrides an already-exported variable."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a hard dep today
        return
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def get_url() -> str:
    """Target URL, always asyncpg-normalised.

    Precedence: `-x db_url=...` on the command line, then
    `config.attributes["db_url"]` (how the pytest fixture points Alembic at the
    throwaway test database), then `DATABASE_URL` from the environment.
    """
    from_cli = (context.get_x_argument(as_dictionary=True) or {}).get("db_url")
    raw = from_cli or config.attributes.get("db_url") or os.getenv(db_session.ENV_VAR)
    if not raw:
        raise RuntimeError(db_session._MISSING_URL_MSG)
    return db_session.async_url(raw)


_load_dotenv()


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(get_url(), poolclass=NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations against a live DB.

    If a caller (e.g. the pytest fixture) has already opened a connection and
    stashed it on `config.attributes["connection"]`, reuse it — that keeps the
    whole migration inside the caller's transaction/event loop.
    """
    existing = config.attributes.get("connection")
    if existing is not None:
        do_run_migrations(existing)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
