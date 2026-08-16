"""The F3 §5 interim-admin removal checklist, pinned at the code level (card L1).

`docs/SPECS/F3.md` §5 lists eight sites where the C0 admin secret lived. Card L1
deletes them. The behavioural half — "no admin-header path authenticates
anything" — is proved in `test_api_auth_f3.py` and `test_api_portfolio.py`; this
file pins the **structural** half: the named functions are gone, so they cannot
quietly grow back, and `ALPHADESK_ADMIN_SECRET` being set changes nothing.

The two remaining sites are outside Python: `frontend/lib/api.ts`'s `ADMIN_SECRET`
(a frontend vitest source scan covers it) and unsetting the variable on the HF
Space (an operator step, `docs/MORNING.md`).
"""

from __future__ import annotations

import pytest

import api.main as main
import api.routes.portfolio as portfolio
import services.adoption as adoption


def test_site_1_admin_secret_accepted_is_gone() -> None:
    assert not hasattr(main, "admin_secret_accepted")


def test_site_2_require_admin_is_gone() -> None:
    assert not hasattr(main, "_require_admin")


def test_site_3_status_identity_takes_no_admin_header() -> None:
    """`_status_identity` no longer has an `x_alphadesk_admin_secret` parameter."""
    import inspect

    params = inspect.signature(main._status_identity).parameters
    assert "x_alphadesk_admin_secret" not in params


def test_site_4_portfolio_admin_identity_is_gone() -> None:
    assert not hasattr(portfolio, "_admin_identity")


def test_site_5_portfolio_identity_takes_no_admin_header() -> None:
    import inspect

    params = inspect.signature(portfolio.portfolio_identity).parameters
    assert "x_alphadesk_admin_secret" not in params


def test_site_6_adoption_admin_identity_is_gone() -> None:
    assert not hasattr(adoption, "admin_identity")


def test_no_module_still_references_the_admin_secret_env() -> None:
    """Grep the shipped Python for the env var: nothing should read it now."""
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in backend.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if "ALPHADESK_ADMIN_SECRET" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(backend)))
    assert offenders == [], f"admin secret still read by: {offenders}"
