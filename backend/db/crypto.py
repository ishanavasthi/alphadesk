"""Symmetric encryption for broker credentials at rest.

Every `*_enc` column in `db.models` holds the output of `encrypt()`: an opaque
Fernet token (URL-safe base64, versioned, HMAC-authenticated). Plaintext access
tokens, refresh tokens and client secrets never touch a column, a log line or
an exception message.

The one credential-ish value stored **in the clear** is
`oauth_pending.verifier` — the PKCE `code_verifier`, per the F1 schema. It is
useless without the matching authorization code and its row is valid for ten
minutes; if that trade stops looking right, `verifier` → `verifier_enc` is a
one-column migration.

Key: env `TOKEN_ENCRYPTION_KEY`, a 32-byte urlsafe-base64 Fernet key. Generate
one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

The key is read lazily on first use (not at import), so the app still boots on
a machine that has not configured one; the failure surfaces the moment
something actually tries to persist or read a credential.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

ENV_VAR = "TOKEN_ENCRYPTION_KEY"

_MISSING_KEY_MSG = (
    f"{ENV_VAR} is not set. AlphaDesk refuses to store or read broker "
    "credentials without an encryption key. Generate one with:\n"
    '  python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"\n'
    f"and put it in backend/.env as {ENV_VAR}=<key>."
)

_BAD_KEY_MSG = (
    f"{ENV_VAR} is not a valid Fernet key (expected 32 url-safe base64-encoded "
    "bytes). Regenerate it with Fernet.generate_key()."
)


class TokenEncryptionError(RuntimeError):
    """Raised when the encryption key is missing/invalid or a token is bad."""


_cached_key: str | None = None
_cached_fernet: Fernet | None = None


def _fernet() -> Fernet:
    """Return a Fernet built from `TOKEN_ENCRYPTION_KEY`, cached per key value.

    Cached on the key *value* so a test (or a key rotation) that changes the
    env var is picked up without a process restart.
    """
    global _cached_key, _cached_fernet

    key = os.getenv(ENV_VAR)
    if not key:
        raise TokenEncryptionError(_MISSING_KEY_MSG)

    if _cached_fernet is not None and _cached_key == key:
        return _cached_fernet

    try:
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        # Deliberately does not echo the key value.
        raise TokenEncryptionError(_BAD_KEY_MSG) from exc

    _cached_key, _cached_fernet = key, fernet
    return fernet


def encrypt(plaintext: str) -> str:
    """Encrypt `plaintext` into an opaque string safe to store in a `*_enc` column."""
    if not isinstance(plaintext, str):
        raise TypeError("encrypt() takes a str; encode bytes yourself first")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a value produced by `encrypt()`.

    Raises `TokenEncryptionError` if the token was not produced by the current
    key or has been tampered with. The message never includes the token.
    """
    if not isinstance(token, str):
        raise TypeError("decrypt() takes a str produced by encrypt()")
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise TokenEncryptionError(
            "Could not decrypt a stored credential: it was encrypted with a "
            f"different {ENV_VAR}, or the stored value is corrupt. Re-link the "
            "broker account to fix."
        ) from exc


def encrypt_optional(plaintext: str | None) -> str | None:
    """`encrypt()` that passes `None` through — for nullable `*_enc` columns."""
    return None if plaintext is None else encrypt(plaintext)


def decrypt_optional(token: str | None) -> str | None:
    """`decrypt()` that passes `None` through — for nullable `*_enc` columns."""
    return None if token is None else decrypt(token)
