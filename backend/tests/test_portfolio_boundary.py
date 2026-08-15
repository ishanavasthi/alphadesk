"""The connector boundary, enforced by grep rather than by good intentions.

`backend/portfolio/connectors/` is the only place a vendor's field names may
appear. Everywhere else — the model, the errors, anything a later card builds on
top — speaks the normalized vocabulary. Without this test the boundary erodes
one convenient `row["pnl_per"]` at a time, and swapping in a second source stops
being possible.

Two greps, deliberately:

- a **code-token** grep (AST-based) that sees identifiers and live string
  literals but *not* docstrings or comments, so a vendor name can be discussed
  in prose while remaining unusable in code. This is the one that catches
  payload parsing, and it covers names like `investment` and `broker` that are
  also ordinary English words;
- a **whole-file** substring grep for the unambiguous names, which additionally
  catches a leak hiding in a comment.

The first grep exists because a real review found `RateLimited.from_body()`
parsing a vendor throttle body inside `errors.py` — above the boundary — while
the whole-file grep of the day passed. It would now fail.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PORTFOLIO = Path(__file__).resolve().parents[1] / "portfolio"
CONNECTORS = PORTFOLIO / "connectors"

#: IND Money's own key names, from `docs/ind_money_payloads.md` §2, plus the
#: throttle-body keys from §2.5. Note what is deliberately NOT here:
#: `invested_amount`, `current_value`, `asset_type` and `market_cap` are the
#: *model's* names too — banning them would be banning our own vocabulary.
VENDOR_FIELD_NAMES = [
    "pnl_per",
    "holding_percent",
    "market_value",
    "investment_code",
    "assetclass_l2",
    "total_networth",
    "total_current_value",
    "total_invested",
    "invested_value",
    "unit_price",
    "total_units",
    "total_pnl",
    "progress_value_percentage",
    "return_percentage",
    "xirr",
    "holding_error",
    "position_error",
    "is_pledge_eligible",
    "is_mtf_pledge_required",
    "intra_day_positions",
    "is_cached_response",
    # Throttle-body keys (§2.5). `scope`, `window`, `limit`, `current` and
    # `cost` are too generic to ban; these two are unmistakably the vendor's.
    "rate_limit_exceeded",
    "retry_after_seconds",
]

#: Vendor names that are also ordinary English. Only the code-token grep can
#: police these — the whole-file grep would trip on any docstring that discusses
#: the source honestly, which is exactly what the docs above the boundary do.
#:
#: ⚠️ `broker` has a known future false positive, and it is not a reason to
#: delete the ban. AlphaDesk's own `backend/broker/` package exposes a
#: `BrokerAdapter`, so the day portfolio code above this boundary references it
#: by name, `ast.Name` will match and this test will fail on a legitimate use.
#: The narrow fix at that point is to keep banning `broker` in **string
#: literals and subscripts** (`row["broker"]`, `"broker"`) — which is where a
#: vendor field name actually leaks — and stop matching bare identifiers.
#: Deleting the entry instead would give up the check that matters.
VENDOR_WORDS_ALSO_ENGLISH = [
    "investment",
    "broker",
]

#: The vendor's tool names are equally leaky: a caller that knows them is
#: coupled to the source it was supposed to be insulated from.
VENDOR_TOOL_NAMES = [
    "networth_snapshot",
    "networth_holdings",
    "networth_allocation_breakdown",
    "mf_sips",
    "indian_stocks_sips",
]

ALL_BANNED = VENDOR_FIELD_NAMES + VENDOR_TOOL_NAMES + VENDOR_WORDS_ALSO_ENGLISH


def files_above_the_boundary() -> list[Path]:
    return sorted(
        path
        for path in PORTFOLIO.rglob("*.py")
        if CONNECTORS not in path.parents and path.parent != CONNECTORS
    )


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Identify the string constants that are docstrings, so prose is exempt."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            out.add(id(body[0].value))
    return out


def code_tokens(path: Path) -> list[str]:
    """Identifiers and live string literals in a module. No docstrings, and —
    since comments never reach the AST — no comments either."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_ids(tree)
    tokens: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.append(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.append(node.attr)
        elif isinstance(node, ast.arg):
            tokens.append(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tokens.append(node.name)
        elif isinstance(node, ast.keyword) and node.arg:
            tokens.append(node.arg)
        elif isinstance(node, ast.alias):
            tokens.extend(t for t in (node.name, node.asname) if t)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skip:
                tokens.append(node.value)
    return tokens


def mentions(name: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None


def test_there_is_something_above_the_boundary_to_check():
    """A vacuous grep passes forever. Prove it has files to look at."""
    names = {path.name for path in files_above_the_boundary()}
    assert {"models.py", "errors.py"} <= names


@pytest.mark.parametrize("name", ALL_BANNED)
def test_no_vendor_name_is_used_in_code_above_the_boundary(name):
    """The load-bearing grep: identifiers and live strings only."""
    offenders = [
        f"{path.relative_to(PORTFOLIO)}::{token[:60]}"
        for path in files_above_the_boundary()
        for token in code_tokens(path)
        if mentions(name, token)
    ]
    assert not offenders, (
        f"vendor name {name!r} is used in code above the connector boundary: "
        f"{offenders} — parsing or naming a vendor field here is what makes a "
        "second source impossible"
    )


@pytest.mark.parametrize("name", VENDOR_FIELD_NAMES + VENDOR_TOOL_NAMES)
def test_no_vendor_name_appears_anywhere_above_the_boundary(name):
    """The unambiguous names must not appear even in a comment."""
    offenders = [
        str(path.relative_to(PORTFOLIO))
        for path in files_above_the_boundary()
        if name in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"vendor name {name!r} leaked above the connector boundary in "
        f"{offenders} — the model must not know what any one source calls its "
        "fields"
    )


def test_the_grep_would_actually_catch_a_leak():
    """Non-vacuity: the same names DO appear below the boundary, so a file that
    moved the wrong way would be caught rather than silently passing."""
    below = [t for path in CONNECTORS.glob("*.py") for t in code_tokens(path)]
    for name in ("pnl_per", "market_value", "investment_code", "networth_holdings",
                 "retry_after_seconds", "rate_limit_exceeded", "investment", "broker"):
        assert any(mentions(name, token) for token in below), (
            f"{name} should be used in connectors/ — if it is not, this grep is "
            "no longer proving anything"
        )


def test_the_code_token_grep_ignores_prose_but_not_code():
    """The two greps differ on purpose; prove the difference is real."""
    tokens = code_tokens(PORTFOLIO / "models.py")
    joined = "\n".join(tokens)
    # The module docstring discusses `invested_amount` returned as 0 by linked
    # *brokers*; the word is prose there and must not be seen as code.
    assert not mentions("broker", joined)
    assert "brokers" in (PORTFOLIO / "models.py").read_text(encoding="utf-8")
    # ... while an actual identifier IS seen.
    assert mentions("invested_amount", joined)


def test_the_model_layer_does_not_import_the_ind_money_client():
    """An import is a leak too, and a harder one to see than a field name."""
    for path in files_above_the_boundary():
        text = path.read_text(encoding="utf-8")
        assert "tools.ind_money" not in text, path
        assert "portfolio.connectors" not in text or path.name == "__init__.py", path
