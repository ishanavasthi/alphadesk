"""`db.session` URL handling, and the test suite's own destructive-DB guard.

No database is touched here — these are pure string/argument assertions plus
one check of what SQLAlchemy would hand `asyncpg.connect()`.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg

from db.session import ASYNC_DRIVER, async_url, normalize_url, sync_url

# Relative on purpose. `backend/` has an __init__.py, so pytest imports this
# file as `backend.tests.test_db_session_url` and the conftest as
# `backend.tests.conftest`; an absolute `from tests.conftest import ...` would
# load a *second* copy of the module and test a different UnsafeTestDatabase
# class than the fixture raises.
from .conftest import (
    DEFAULT_TEST_DB_URL,
    UnsafeTestDatabase,
    resolve_test_database_url,
)

#: The shape Neon actually hands you when you copy the connection string.
NEON_URL = (
    "postgresql://alphadesk_owner:npg_secret@ep-cool-name-123456.eu-central-1"
    ".aws.neon.tech/alphadesk?sslmode=require&channel_binding=require"
)


# --------------------------------------------------------------------------
# scheme normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://u:p@h:5432/db",
        "postgres://u:p@h:5432/db",
        "postgresql+asyncpg://u:p@h:5432/db",
    ],
)
def test_every_postgres_spelling_normalises_to_asyncpg(raw: str) -> None:
    assert async_url(raw) == "postgresql+asyncpg://u:p@h:5432/db"


def test_sync_url_drops_the_driver() -> None:
    assert sync_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"


def test_non_postgres_urls_are_left_alone() -> None:
    assert async_url("sqlite+aiosqlite:///./x.db") == "sqlite+aiosqlite:///./x.db"


def test_credentials_and_path_survive_normalisation() -> None:
    parts = urlsplit(async_url(NEON_URL))
    assert parts.username == "alphadesk_owner"
    assert parts.password == "npg_secret"
    assert parts.hostname == "ep-cool-name-123456.eu-central-1.aws.neon.tech"
    assert parts.path == "/alphadesk"


# --------------------------------------------------------------------------
# libpq query params asyncpg cannot accept
# --------------------------------------------------------------------------


def test_neon_url_query_is_translated_for_asyncpg() -> None:
    """`sslmode` becomes asyncpg's `ssl`; `channel_binding` is dropped."""
    query = parse_qs(urlsplit(async_url(NEON_URL)).query)
    assert query == {"ssl": ["require"]}


def test_sync_url_keeps_libpq_params() -> None:
    """libpq-based drivers do understand sslmode — only asyncpg needs the fix."""
    query = parse_qs(urlsplit(sync_url(NEON_URL)).query)
    assert query == {"sslmode": ["require"], "channel_binding": ["require"]}


def test_an_explicit_ssl_param_wins_over_sslmode() -> None:
    url = async_url("postgresql://u:p@h/db?ssl=verify-full&sslmode=require")
    assert parse_qs(urlsplit(url).query) == {"ssl": ["verify-full"]}


def test_unrelated_query_params_are_preserved() -> None:
    url = async_url("postgresql://u:p@h/db?sslmode=require&application_name=alphaDesk")
    assert parse_qs(urlsplit(url).query) == {
        "ssl": ["require"],
        "application_name": ["alphaDesk"],
    }


def test_asyncpg_connect_kwargs_from_a_neon_url_are_all_accepted() -> None:
    """The finding this test exists for: SQLAlchemy splats the query string
    into `asyncpg.connect()`, so a leftover `sslmode`/`channel_binding` is a
    TypeError on the first connection, not a warning."""
    import inspect

    import asyncpg

    _, opts = PGDialect_asyncpg().create_connect_args(make_url(async_url(NEON_URL)))

    signature = inspect.signature(asyncpg.connect)
    assert not any(
        p.kind is p.VAR_KEYWORD for p in signature.parameters.values()
    ), "asyncpg.connect grew **kwargs; this test no longer proves anything"

    accepted = set(signature.parameters)
    assert "ssl" in opts
    assert "sslmode" not in opts
    assert "channel_binding" not in opts
    assert set(opts) <= accepted, f"asyncpg would reject: {set(opts) - accepted}"

    # And the un-normalised URL really would have blown up.
    _, raw_opts = PGDialect_asyncpg().create_connect_args(
        make_url(NEON_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    )
    assert set(raw_opts) - accepted == {"sslmode", "channel_binding"}


# --------------------------------------------------------------------------
# the suite's own guard against dropping someone's real database
# --------------------------------------------------------------------------


def test_no_env_falls_back_to_the_local_default() -> None:
    assert resolve_test_database_url(None, None) == async_url(DEFAULT_TEST_DB_URL)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_loopback_database_url_is_inherited(host: str) -> None:
    url = f"postgresql://postgres:test@{host}:5433/alphadesk"
    assert resolve_test_database_url(None, url) == async_url(url)


@pytest.mark.parametrize(
    "url",
    [
        NEON_URL,
        "postgresql://u:p@db.internal.example.com/alphadesk",
        "postgresql://u:p@10.0.0.7/alphadesk",
    ],
)
def test_remote_database_url_is_refused(url: str) -> None:
    """A leftover DATABASE_URL export must not get a DROP DATABASE."""
    with pytest.raises(UnsafeTestDatabase) as excinfo:
        resolve_test_database_url(None, url)
    message = str(excinfo.value)
    assert "TEST_DATABASE_URL" in message
    assert "DROP" in message


def test_test_database_url_is_trusted_even_when_remote() -> None:
    """Naming the host explicitly *is* the confirmation."""
    assert resolve_test_database_url(NEON_URL, None) == async_url(NEON_URL)


def test_test_database_url_wins_over_database_url() -> None:
    local = "postgresql://postgres:test@localhost:5433/alphadesk"
    assert resolve_test_database_url(local, NEON_URL) == async_url(local)


def test_normalize_url_default_driver_is_asyncpg() -> None:
    assert normalize_url("postgresql://u:p@h/db").startswith(ASYNC_DRIVER + "://")
