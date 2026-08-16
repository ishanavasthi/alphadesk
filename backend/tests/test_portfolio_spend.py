"""Spend ceilings (card A1, item 7) — both caps, and the day-boundary reset."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.portfolio.spend import SpendLimiter


def test_global_daily_cap_denies_across_users(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVERVIEW_DAILY_GLOBAL_MAX", "2")
    monkeypatch.setenv("OVERVIEW_DAILY_USER_MAX", "100")  # not the binding cap
    limiter = SpendLimiter()

    assert limiter.reserve("alice").allowed is True
    assert limiter.reserve("bob").allowed is True
    # The third reservation, from a THIRD user, is denied by the global ceiling.
    third = limiter.reserve("carol")
    assert third.allowed is False
    assert third.reason == "global_daily_cap"


def test_per_user_cap_denies_one_noisy_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVERVIEW_DAILY_GLOBAL_MAX", "100")
    monkeypatch.setenv("OVERVIEW_DAILY_USER_MAX", "1")
    limiter = SpendLimiter()

    assert limiter.reserve("alice").allowed is True
    denied = limiter.reserve("alice")
    assert denied.allowed is False
    assert denied.reason == "user_daily_cap"
    # A different user is unaffected.
    assert limiter.reserve("bob").allowed is True


def test_release_refunds_a_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVERVIEW_DAILY_GLOBAL_MAX", "1")
    monkeypatch.setenv("OVERVIEW_DAILY_USER_MAX", "1")
    limiter = SpendLimiter()

    assert limiter.reserve("alice").allowed is True
    assert limiter.reserve("alice").allowed is False
    limiter.release("alice")  # the run never happened
    assert limiter.reserve("alice").allowed is True


def test_counts_reset_on_the_utc_day_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OVERVIEW_DAILY_GLOBAL_MAX", "1")
    monkeypatch.setenv("OVERVIEW_DAILY_USER_MAX", "1")
    limiter = SpendLimiter()

    day1 = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
    day2 = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    assert limiter.reserve("alice", now=day1).allowed is True
    assert limiter.reserve("alice", now=day1).allowed is False
    # A new UTC day resets both counters.
    assert limiter.reserve("alice", now=day2).allowed is True
