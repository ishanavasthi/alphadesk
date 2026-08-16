"""`redact()` (card A1, item 2) — no PII class survives a prompt payload."""

from __future__ import annotations

from agents.portfolio.redact import REDACTED, contains_pii, redact


def _payload() -> dict:
    """One payload carrying every forbidden class at once (§8.1)."""
    return {
        "user_id": "user_2abcDEF",  # Clerk id
        "clerk_id": "user_2abcDEF",
        "account_number": "123456789012",
        "broker": "some-broker-code",
        "broker_id": "BRK-99",
        "email": "operator@example.com",
        "access_token_enc": "gAAAAABxxxxxxxxxxxxxxxxxxxxxxxxx",
        "refresh_token": "rt_verylongopaquevalue1234567890",
        "client_secret": "cs_anotheropaquesecretvalue123456",
        "pan": "ABCDE1234F",
        "nested": {
            "email": "someone@else.org",
            "holding": {
                "symbol": "DEMOANVIL",  # allowed: an instrument symbol
                "name": "Demo Anvil Industries Ltd",  # allowed
                "current_value": "222780.00",  # allowed: an aggregate
                "investment_code": "IND00577",  # a vendor instrument id: drop
            },
        },
        "list_of_contacts": ["a@b.com", "plain text", {"phone": "+919999999999"}],
        "equity_share": "39.0%",  # allowed
    }


def test_every_pii_class_is_stripped() -> None:
    cleaned = redact(_payload())
    assert not contains_pii(cleaned)


def test_forbidden_keys_are_gone() -> None:
    cleaned = redact(_payload())
    for banned in (
        "user_id",
        "clerk_id",
        "account_number",
        "broker",
        "broker_id",
        "email",
        "access_token_enc",
        "refresh_token",
        "client_secret",
        "pan",
    ):
        assert banned not in cleaned
    assert "email" not in cleaned["nested"]
    assert "investment_code" not in cleaned["nested"]["holding"]


def test_allowed_aggregates_and_symbols_survive() -> None:
    cleaned = redact(_payload())
    holding = cleaned["nested"]["holding"]
    assert holding["symbol"] == "DEMOANVIL"
    assert holding["name"] == "Demo Anvil Industries Ltd"
    assert holding["current_value"] == "222780.00"
    assert cleaned["equity_share"] == "39.0%"


def test_email_shaped_value_under_innocent_key_is_redacted() -> None:
    cleaned = redact({"note": "reach me at ops@example.com please"})
    assert cleaned["note"] == REDACTED


def test_list_elements_are_scrubbed() -> None:
    cleaned = redact(_payload())
    contacts = cleaned["list_of_contacts"]
    assert contacts[0] == REDACTED  # email string
    assert contacts[1] == "plain text"
    assert "phone" not in contacts[2]


def test_numbers_and_none_pass_through() -> None:
    assert redact({"weight_pct": 39.0, "missing": None, "flag": True}) == {
        "weight_pct": 39.0,
        "missing": None,
        "flag": True,
    }
