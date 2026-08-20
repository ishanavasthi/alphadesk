"""The manual-FD accrual math (card B10) — pure, no database, no HTTP.

Every expected figure below is **hand-computed** and shown as the arithmetic
that produced it, because these numbers are the feature: the whole point of
card B10 is that a fixed deposit's value is derived from its terms rather than
read off a payload, so a wrong formula here is a wrong number on someone's net
worth with nothing upstream to contradict it.

The five conventions are pinned at whole numbers of compounding periods, where
the closed form is checkable by hand. The fractional-exponent approximation gets
its own test, bracketed between the two whole periods it sits between.

The two clamps — nothing before `start_date`, frozen at `maturity_date` — are
tested as behaviour rather than as arithmetic: they are the rules that stop the
card from inventing interest.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import date
from decimal import Decimal

import pytest

from services import manual_fd
from services.manual_fd import valuation, value_at, year_fraction

START = date(2025, 1, 1)
MATURITY = date(2026, 1, 1)  # exactly 365 days -> t = 1
LAKH = Decimal("100000")


def _value(
    compounding: str,
    *,
    principal: Decimal = LAKH,
    rate_pct: Decimal = Decimal("8"),
    start: date = START,
    maturity: date = MATURITY,
    as_of: date = MATURITY,
) -> Decimal:
    return valuation(principal, rate_pct, compounding, start, maturity, as_of).current_value


# --------------------------------------------------------------------------- #
# 1. The five conventions, at whole compounding periods
# --------------------------------------------------------------------------- #
def test_quarterly_over_one_year() -> None:
    """100000 x (1 + 0.08/4)^4 = 100000 x 1.02^4 = 100000 x 1.08243216."""
    assert _value("quarterly", rate_pct=Decimal("8")) == Decimal("108243.22")


def test_monthly_over_one_year() -> None:
    """100000 x (1 + 0.12/12)^12 = 100000 x 1.01^12 = 100000 x 1.1268250301..."""
    assert _value("monthly", rate_pct=Decimal("12")) == Decimal("112682.50")


def test_half_yearly_over_one_year() -> None:
    """100000 x (1 + 0.10/2)^2 = 100000 x 1.05^2 = 100000 x 1.1025 exactly."""
    assert _value("half_yearly", rate_pct=Decimal("10")) == Decimal("110250.00")


def test_yearly_over_one_year() -> None:
    """100000 x (1 + 0.10/1)^1 = 110000 exactly."""
    assert _value("yearly", rate_pct=Decimal("10")) == Decimal("110000.00")


def test_simple_interest_over_two_years() -> None:
    """200000 x (1 + 0.06 x 2) = 200000 x 1.12 = 224000 exactly.

    2025-01-01 -> 2027-01-01 is 730 days, so t = 2 under actual/365.
    """
    assert (
        _value(
            "simple",
            principal=Decimal("200000"),
            rate_pct=Decimal("6"),
            maturity=date(2027, 1, 1),
            as_of=date(2027, 1, 1),
        )
        == Decimal("224000.00")
    )


def test_simple_and_compound_diverge_on_the_same_terms() -> None:
    """The two formulas are genuinely different code paths, not a shared one.

    Over a year at 10%: yearly compounding and simple interest agree (one
    period), but half-yearly does not — 1.05^2 = 1.1025 against 1.10.
    """
    simple = _value("simple", rate_pct=Decimal("10"))
    assert simple == _value("yearly", rate_pct=Decimal("10"))
    assert simple < _value("half_yearly", rate_pct=Decimal("10"))
    assert _value("half_yearly", rate_pct=Decimal("10")) < _value(
        "monthly", rate_pct=Decimal("10")
    )


def test_unknown_compounding_raises_rather_than_guessing() -> None:
    with pytest.raises(ValueError, match="unknown compounding"):
        value_at(LAKH, Decimal("8"), "fortnightly", Decimal(1))


# --------------------------------------------------------------------------- #
# 2. The fractional-period approximation
# --------------------------------------------------------------------------- #
def test_partial_period_uses_a_fractional_exponent() -> None:
    """182 days of a quarterly 8% lakh: t = 182/365, exponent = 728/365.

    100000 x 1.02^1.99452054... = 104028.71 (1.02^2 = 1.0404, discounted by
    1.02^0.00548 ~ 1.0001085). Documented as an approximation of a bank's
    partial-period rules — it agrees exactly on period boundaries and differs by
    rupees, not percent, in between.
    """
    at_182 = _value("quarterly", as_of=date(2025, 7, 2))
    assert at_182 == Decimal("104028.71")


def test_a_partial_period_sits_between_the_periods_it_straddles() -> None:
    """The property the approximation must never break: monotonic, and bounded
    by the whole periods on either side.

    Three quarters of a year at 8% quarterly is between 1.02^2 (=104040) and
    1.02^3 (=106120.80) nowhere near either bound being crossed.
    """
    two_quarters = LAKH * Decimal("1.02") ** 2
    three_quarters = LAKH * Decimal("1.02") ** 3
    mid = _value("quarterly", as_of=date(2025, 8, 1))  # 212 days
    assert two_quarters < mid < three_quarters


# --------------------------------------------------------------------------- #
# 3. The two clamps — where the honesty lives
# --------------------------------------------------------------------------- #
def test_a_deposit_that_has_not_started_has_earned_nothing() -> None:
    """Before `start_date` the value is the principal, and not a rupee more."""
    result = valuation(LAKH, Decimal("8"), "quarterly", START, MATURITY, date(2024, 6, 1))
    assert result.current_value == LAKH
    assert result.accrued_interest == Decimal("0.00")
    assert result.matured is False


def test_year_fraction_is_zero_before_the_start_and_never_negative() -> None:
    assert year_fraction(START, MATURITY, date(2024, 1, 1)) == Decimal(0)
    assert year_fraction(START, MATURITY, START) == Decimal(0)


def test_value_freezes_at_maturity_and_never_accrues_past_the_term() -> None:
    """Four years after a one-year deposit matured it is worth what it was worth
    on the day it matured — a deposit does not keep compounding because nobody
    closed the browser tab."""
    at_maturity = valuation(LAKH, Decimal("8"), "quarterly", START, MATURITY, MATURITY)
    much_later = valuation(
        LAKH, Decimal("8"), "quarterly", START, MATURITY, date(2030, 1, 1)
    )
    assert much_later.current_value == at_maturity.current_value == Decimal("108243.22")
    assert much_later.maturity_value == at_maturity.current_value
    assert much_later.matured is True


def test_matured_flips_on_the_maturity_date_itself() -> None:
    day_before = valuation(
        LAKH, Decimal("8"), "quarterly", START, MATURITY, date(2025, 12, 31)
    )
    on_the_day = valuation(LAKH, Decimal("8"), "quarterly", START, MATURITY, MATURITY)
    assert day_before.matured is False
    assert day_before.days_to_maturity == 1
    assert on_the_day.matured is True
    assert on_the_day.days_to_maturity == 0


def test_days_to_maturity_floors_at_zero() -> None:
    """A matured deposit is not "-1461 days away"; `matured` is what says so."""
    result = valuation(LAKH, Decimal("8"), "quarterly", START, MATURITY, date(2030, 1, 1))
    assert result.days_to_maturity == 0


# --------------------------------------------------------------------------- #
# 4. Invariants
# --------------------------------------------------------------------------- #
def test_accrued_interest_is_always_value_minus_principal() -> None:
    for as_of in (date(2024, 1, 1), date(2025, 7, 2), MATURITY, date(2030, 1, 1)):
        result = valuation(LAKH, Decimal("8"), "quarterly", START, MATURITY, as_of)
        assert result.accrued_interest == result.current_value - LAKH


def test_maturity_value_is_the_same_number_whenever_it_is_asked_for() -> None:
    """`maturity_value` must not depend on `as_of` — it is a property of the
    terms, and a card that showed a different one before and after maturity
    would be reporting two different deposits."""
    values = {
        valuation(LAKH, Decimal("8"), "quarterly", START, MATURITY, as_of).maturity_value
        for as_of in (date(2024, 1, 1), date(2025, 6, 1), MATURITY, date(2030, 1, 1))
    }
    assert values == {Decimal("108243.22")}


def test_every_figure_is_a_decimal_and_quantized_to_paise() -> None:
    result = valuation(LAKH, Decimal("7.1875"), "quarterly", START, MATURITY, date(2025, 9, 9))
    for figure in (result.current_value, result.accrued_interest, result.maturity_value):
        assert isinstance(figure, Decimal)
        assert -figure.as_tuple().exponent == 2


def test_the_module_contains_no_float_anywhere() -> None:
    """The acceptance criterion, enforced against the source itself.

    A single `float(...)` or float literal in this module would silently
    reintroduce the binary rounding M1 spent a card eliminating — and it would
    be invisible, because a float answer looks right to two decimal places
    until the day it does not.
    """
    source = pathlib.Path(manual_fd.__file__).read_text()
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offenders.append(f"float literal {node.value!r} on line {node.lineno}")
        if isinstance(node, ast.Name) and node.id == "float":
            offenders.append(f"reference to `float` on line {node.lineno}")
    assert not offenders, offenders
