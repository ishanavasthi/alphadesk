"""App-side spend ceilings for the AI overview (card A1, item 7).

Two in-code, configurable ceilings guard OpenAI spend, and **both fail toward
the degraded state, never toward an error**: when a ceiling is hit the overview
still renders every computed number and simply shows "AI overview unavailable".

- a **global** daily ceiling — the whole app's overview generations per UTC day;
- a low **per-user** daily cap — one noisy user cannot drain the global budget.

This is the cheap, always-on guard. The real hard stop is a provider-side budget
cap on the OpenAI dashboard (an operator task, noted in ``MORNING.md``); this
one exists so a runaway loop degrades gracefully long before that bill lands.

State is in-memory and per-process — consistent with the rest of the Lab/overview
state (CLAUDE.md), and appropriate for a ceiling whose job is "stop a loop", not
"bill accurately across replicas". Counts reset on the UTC day boundary.
"""

from __future__ import annotations

import os
import threading
from datetime import date, datetime, timezone
from typing import Optional

#: Defaults are deliberately modest; override per deployment.
_DEFAULT_GLOBAL_DAILY = 500
_DEFAULT_USER_DAILY = 20

_GLOBAL_ENV = "OVERVIEW_DAILY_GLOBAL_MAX"
_USER_ENV = "OVERVIEW_DAILY_USER_MAX"


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


class SpendLimiter:
    """Counts overview generations against a global and a per-user daily cap.

    ``reserve(user_id)`` is the one call sites use: it returns a
    :class:`SpendDecision`. If ``allowed`` is False the caller degrades — it does
    not raise, because a spend ceiling is an expected state, not a fault.
    Reads the caps from the environment on **every** call so an operator can
    retune them without a restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: Optional[date] = None
        self._global_count = 0
        self._per_user: dict[str, int] = {}

    def _roll(self, today: date) -> None:
        if self._day != today:
            self._day = today
            self._global_count = 0
            self._per_user = {}

    def reserve(self, user_id: str, *, now: Optional[datetime] = None) -> "SpendDecision":
        now = now or datetime.now(timezone.utc)
        today = now.astimezone(timezone.utc).date()
        global_max = _int_env(_GLOBAL_ENV, _DEFAULT_GLOBAL_DAILY)
        user_max = _int_env(_USER_ENV, _DEFAULT_USER_DAILY)
        with self._lock:
            self._roll(today)
            if self._global_count >= global_max:
                return SpendDecision(False, "global_daily_cap", global_max, self._global_count)
            used = self._per_user.get(user_id, 0)
            if used >= user_max:
                return SpendDecision(False, "user_daily_cap", user_max, used)
            self._global_count += 1
            self._per_user[user_id] = used + 1
            return SpendDecision(True, None, global_max, self._global_count)

    def release(self, user_id: str) -> None:
        """Give a reservation back — call when the generation never happened.

        Used when ``reserve`` said yes but the LLM was unavailable for another
        reason, so a degraded run does not burn a slot it never spent.
        """
        with self._lock:
            if self._global_count > 0:
                self._global_count -= 1
            used = self._per_user.get(user_id, 0)
            if used > 0:
                self._per_user[user_id] = used - 1

    def forget_user(self, user_id: str) -> None:
        """Drop a deleted user's per-user tally (card L1, delete-my-data).

        No PII lives here — just a count — but a deleted id should not keep a slot
        in the per-user map, for symmetry with the rest of the erase path. The
        global count is left alone: it is the whole app's budget, not this user's.
        """
        with self._lock:
            self._per_user.pop(user_id, None)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"global": self._global_count, "users": len(self._per_user)}

    def reset(self) -> None:
        with self._lock:
            self._day = None
            self._global_count = 0
            self._per_user = {}


class SpendDecision:
    __slots__ = ("allowed", "reason", "limit", "used")

    def __init__(self, allowed: bool, reason: Optional[str], limit: int, used: int) -> None:
        self.allowed = allowed
        self.reason = reason
        self.limit = limit
        self.used = used


#: Process-wide limiter shared by the overview route.
_LIMITER = SpendLimiter()


def get_limiter() -> SpendLimiter:
    return _LIMITER


__all__ = ["SpendDecision", "SpendLimiter", "get_limiter"]
