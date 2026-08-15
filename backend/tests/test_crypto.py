"""`db.crypto` — the contract every `*_enc` column depends on."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from db import crypto

SECRET = "ind-money-access-token-AbCd1234-super-secret"


def test_round_trip_is_identity() -> None:
    assert crypto.decrypt(crypto.encrypt(SECRET)) == SECRET


def test_ciphertext_does_not_contain_plaintext() -> None:
    token = crypto.encrypt(SECRET)
    assert token != SECRET
    assert SECRET not in token
    # No fragment of the secret survives either — not even a substring long
    # enough to be recognisable.
    for i in range(0, len(SECRET) - 8):
        assert SECRET[i : i + 8] not in token


def test_encryption_is_non_deterministic() -> None:
    """Fernet embeds a random IV, so the same input never yields the same
    ciphertext twice — an attacker with read access cannot tell which two users
    linked with the same token."""
    assert crypto.encrypt(SECRET) != crypto.encrypt(SECRET)


def test_round_trip_survives_unicode_and_empty_strings() -> None:
    for value in ["", "  ", "₹ अल्फा", "a" * 4096]:
        assert crypto.decrypt(crypto.encrypt(value)) == value


def test_missing_key_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(crypto.TokenEncryptionError) as excinfo:
        crypto.encrypt(SECRET)
    message = str(excinfo.value)
    assert "TOKEN_ENCRYPTION_KEY" in message
    assert "Fernet.generate_key" in message


def test_invalid_key_raises_without_echoing_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(crypto.TokenEncryptionError) as excinfo:
        crypto.encrypt(SECRET)
    assert "not-a-fernet-key" not in str(excinfo.value)


def test_decrypt_with_a_different_key_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = crypto.encrypt(SECRET)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(crypto.TokenEncryptionError) as excinfo:
        crypto.decrypt(token)
    assert token not in str(excinfo.value)


def test_tampered_ciphertext_is_rejected() -> None:
    token = crypto.encrypt(SECRET)
    flipped = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    with pytest.raises(crypto.TokenEncryptionError):
        crypto.decrypt(flipped)


def test_optional_helpers_pass_none_through() -> None:
    assert crypto.encrypt_optional(None) is None
    assert crypto.decrypt_optional(None) is None
    assert crypto.decrypt_optional(crypto.encrypt_optional(SECRET)) == SECRET
