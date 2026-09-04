"""Environment hygiene for the suite (issue #31).

A test suite whose result depends on the operator's `backend/.env` — and which
can point a process-global engine at a production database — is the bug this
file pins shut. `tests/conftest.py` scrubs the session at import and sets
`ALPHADESK_TESTING=1` so `api.main` skips `load_dotenv()`; these tests assert
both halves hold, including after the app itself is imported.
"""

from __future__ import annotations

import os

import pytest


def _leaked_ind_money_vars() -> list[str]:
    return sorted(v for v in os.environ if v.startswith("IND_MONEY_"))


def test_testing_flag_is_set() -> None:
    assert os.environ.get("ALPHADESK_TESTING") == "1"


def test_no_database_url_without_a_fixture() -> None:
    assert "DATABASE_URL" not in os.environ


def test_no_single_tenant_without_a_fixture() -> None:
    assert "ALPHADESK_SINGLE_TENANT" not in os.environ


def test_no_ind_money_vars_without_a_fixture() -> None:
    assert _leaked_ind_money_vars() == []


@pytest.mark.parametrize(
    "var",
    [
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "NVIDIA_API_KEY",
        "BAI_API_KEY",
        "OVERVIEW_PROVIDER",
        "OVERVIEW_MODEL",
        "LAB_PROVIDER",
        "LAB_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_COMPATIBLE_MODEL",
        "CLERK_JWKS_URL",
        "CLERK_ISSUER",
        "CRON_SECRET",
    ],
)
def test_no_provider_or_infra_vars_without_a_fixture(var: str) -> None:
    assert var not in os.environ


def test_importing_the_app_introduces_no_dotfile() -> None:
    """`api.main` must not `load_dotenv()` under pytest (issue #31, step 2)."""
    before = dict(os.environ)
    import api.main  # noqa: F401

    assert dict(os.environ) == before
