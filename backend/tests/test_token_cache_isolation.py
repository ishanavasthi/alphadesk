"""The suite can never write the operator's real token cache.

This is a regression test for a bug that cost a live broker link.

`_persist_file()` mirrors credentials to `backend/.ind_money_token.json`
whenever `_is_local_dev()` is true — that is, `ALPHADESK_SINGLE_TENANT=1` and
the user is `local`. Both halves are true *inside the test suite* on an
operator's machine, because `api.main` calls `load_dotenv()` at import and a
real `backend/.env` sets exactly that flag.

Three tests monkeypatched `_CACHE_FILE` to a `tmp_path`. Every other test that
reached a persist wrote to the real file instead, and the OAuth stub's fixture
values (`acc-1`, `ref-1`, `cli-1`, `sec-1`) replaced a working credential. The
next login then sent `client_id=cli-1` to IND Money and was rejected with
"Client ID 'cli-1' not found" — a dead link with no obvious cause.

Per-test opt-in was the wrong shape: it is a rule that has to be remembered
every time somebody adds a test that touches the store. The fixture in
`conftest.py` makes it unforgettable, and these tests fail if it is removed.
"""

from __future__ import annotations

from pathlib import Path

from tools import ind_money_auth as auth

#: The path the module would use with no fixture in the way.
REAL_CACHE_FILE = Path(auth.__file__).resolve().parents[1] / ".ind_money_token.json"


def test_cache_file_is_redirected_away_from_the_repo() -> None:
    """The single invariant. If this fails, a test run can eat a real link."""
    assert auth._CACHE_FILE != REAL_CACHE_FILE
    assert REAL_CACHE_FILE not in auth._CACHE_FILE.parents


def test_persisting_does_not_touch_the_real_file() -> None:
    """Drive the write path that caused the incident and check the blast radius.

    `_persist_file` is called for real — not stubbed — with the single-tenant
    conditions that made it fire in the first place.
    """
    existed_before = REAL_CACHE_FILE.exists()
    before = REAL_CACHE_FILE.read_bytes() if existed_before else None

    store = auth.AuthStore(user_id=auth.LOCAL_USER_ID)
    store._access = "test-access"
    store._refresh = "test-refresh"
    store._client_id = "test-client"
    store._persist_file()

    # The redirected file got the write...
    assert auth._CACHE_FILE.exists()
    assert "test-client" in auth._CACHE_FILE.read_text(encoding="utf-8")

    # ...and the operator's real one is exactly as it was.
    assert REAL_CACHE_FILE.exists() is existed_before
    if existed_before:
        assert REAL_CACHE_FILE.read_bytes() == before


def test_hydration_cannot_read_the_operator_credential() -> None:
    """The read direction matters too.

    A test that hydrated from the real file would pass or fail depending on
    whether the developer happened to be logged in to IND Money.
    """
    assert auth._CACHE_FILE != REAL_CACHE_FILE
