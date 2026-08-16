"""`redact()` — the scrubber every LLM prompt payload is routed through (§8.1).

The overview sends the model **aggregates and instrument symbols only**. It must
never send account numbers, broker ids, emails, or the Clerk ``user_id`` — the
model is a third party, and holdings are already kept off LangSmith (F1). A
prompt is built from the computed metric dict, which is clean by construction,
but ``redact()`` is the belt-and-braces gate: it is applied to whatever a caller
hands it, and a test feeds it a payload carrying every forbidden class at once
and asserts none survives.

The policy is **deny by key and deny by value**:

- keys whose name matches a PII class (account/broker/email/user id/token/…) are
  dropped wholesale, however deeply nested;
- string values that *look* like an email are dropped even under an innocent key,
  because the label a leak arrives under is not something we control.

It fails safe: an unknown structure is walked recursively, and anything it cannot
prove is safe (a key it does not recognise carrying a PII-shaped value) is
removed, not passed through.
"""

from __future__ import annotations

import re
from typing import Any

#: Substrings that, appearing in a key, mark the whole value as PII to drop.
#: Matched case-insensitively against the key with separators removed, so
#: ``user_id``, ``userId`` and ``USER-ID`` all match ``userid``.
_DENY_KEY_SUBSTRINGS = (
    "userid",
    "clerkid",
    "accountnumber",
    "accountno",
    "accountid",
    "acctnumber",
    "brokerid",
    "brokercode",
    "broker",
    "email",
    "phone",
    "mobile",
    "pan",
    "aadhaar",
    "aadhar",
    "token",
    "secret",
    "password",
    "apikey",
    "refresh",
    "access",
    "authorization",
    "clientsecret",
    "clientid",
    "ssn",
    "ifsc",
    "folio",
    "demat",
    "externalid",
    "investmentcode",
)

#: A key that is exactly one of these is dropped even though its normalized form
#: is short (``pan``, ``sub`` for the JWT subject).
_DENY_KEY_EXACT = frozenset({"pan", "sub", "iss", "aud", "sid", "azp"})

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

#: A crude "looks like a long opaque id / token" test: a run of >= 20 chars with
#: no spaces mixing letters and digits. Deliberately conservative so ordinary
#: prose and money strings are never dropped.
_OPAQUE_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_\-+/=]{20,}$")

#: Redaction sentinel — present so a reviewer can see a field was scrubbed
#: rather than silently absent.
REDACTED = "[redacted]"


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _key_is_pii(key: str) -> bool:
    norm = _norm_key(key)
    if key.lower() in _DENY_KEY_EXACT or norm in _DENY_KEY_EXACT:
        return True
    return any(sub in norm for sub in _DENY_KEY_SUBSTRINGS)


def _value_is_pii(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if _EMAIL_RE.search(text):
        return True
    if _OPAQUE_RE.match(text):
        return True
    return False


def redact(payload: Any) -> Any:
    """Return a deep copy of ``payload`` with every PII class removed.

    - ``dict`` — keys matching a PII class are dropped; the rest are recursed.
    - ``list`` / ``tuple`` — each element is recursed.
    - ``str`` — an email- or opaque-id-shaped value becomes ``REDACTED``.
    - anything else — returned unchanged (numbers, bools, ``None``).
    """
    if isinstance(payload, dict):
        out: dict[Any, Any] = {}
        for key, value in payload.items():
            if isinstance(key, str) and _key_is_pii(key):
                continue
            out[key] = redact(value)
        return out
    if isinstance(payload, (list, tuple)):
        return [redact(item) for item in payload]
    if isinstance(payload, str):
        return REDACTED if _value_is_pii(payload) else payload
    return payload


def contains_pii(payload: Any) -> bool:
    """Whether ``payload`` still carries any PII class — for test assertions."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and _key_is_pii(key):
                return True
            if contains_pii(value):
                return True
        return False
    if isinstance(payload, (list, tuple)):
        return any(contains_pii(item) for item in payload)
    if isinstance(payload, str):
        return _value_is_pii(payload)
    return False


__all__ = ["REDACTED", "contains_pii", "redact"]
