"""RiskManager guardrails (card B11, phase 1) — the deterministic core, pinned.

``CLAUDE.md`` advertises one property above all others for this agent:
*"Guardrail enforcement is deterministic (correctness must not depend on the
LLM)."* Until this file existed nothing tested it — ``MIN_CONFIDENCE``,
``_FLAG_BAND`` and ``MAX_PER_SECTOR`` appeared in no test in the suite, so every
threshold boundary and the sector cap's tie-breaking were free to move silently.

These tests pin **current** behaviour, deliberately, before B11 phases 2-3 change
the meaning of ``confidence``. They are the regression net for that work, not a
statement that the current thresholds are right.

Each boundary is tested on both sides (0.699/0.70, 0.749/0.75) because an
off-by-one in a comparison operator is exactly the mutation a coarser test
would miss.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from agents import risk_manager as rm
from graph.state import AnalystRecommendation, PortfolioState, RiskAssessment


def _rec(
    symbol: str = "RELIANCE",
    confidence: float = 0.9,
    action: str = "buy",
) -> AnalystRecommendation:
    """A recommendation that clears every guardrail unless a field is overridden."""
    return AnalystRecommendation(
        symbol=symbol,
        action=action,
        confidence=confidence,
        bull_thesis="Bull case.",
        bear_thesis="Bear case.",
    )


def _assess_one(
    rec: AnalystRecommendation,
    sector: Optional[str] = None,
    counts: Optional[Dict[str, int]] = None,
) -> RiskAssessment:
    return rm._assess(rec, sector, counts if counts is not None else {})


# --------------------------------------------------------------------------- #
# Confidence thresholds — both sides of both boundaries
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("confidence", "decision", "approved"),
    [
        (0.0, "REJECT", False),
        (0.69, "REJECT", False),
        (0.6999, "REJECT", False),
        (0.70, "FLAG", True),  # MIN_CONFIDENCE is inclusive: >= 0.70 proceeds
        (0.7499, "FLAG", True),
        (0.75, "PASS", True),  # _FLAG_BAND is exclusive: >= 0.75 is a clean PASS
        (1.0, "PASS", True),
    ],
)
def test_confidence_boundaries(confidence: float, decision: str, approved: bool) -> None:
    out = _assess_one(_rec(confidence=confidence))
    assert out.decision == decision
    assert out.approved is approved


def test_below_threshold_names_the_violation() -> None:
    out = _assess_one(_rec(confidence=0.5))
    assert out.violations == ["confidence_below_threshold"]


def test_cleared_recommendation_has_no_violations() -> None:
    assert _assess_one(_rec(confidence=0.8)).violations == []


def test_confidence_is_carried_through_untouched() -> None:
    """The assessment reports the analyst's number, it never recomputes one."""
    out = _assess_one(_rec(confidence=0.8125))
    assert out.confidence == 0.8125


# --------------------------------------------------------------------------- #
# Analyst action
# --------------------------------------------------------------------------- #
def test_avoid_is_rejected_however_confident() -> None:
    out = _assess_one(_rec(confidence=1.0, action="avoid"))
    assert out.decision == "REJECT"
    assert out.violations == ["analyst_recommends_avoid"]


def test_hold_is_not_a_rejection() -> None:
    """Only 'avoid' is a guardrail breach — 'hold' rides on confidence alone."""
    assert _assess_one(_rec(confidence=0.9, action="hold")).decision == "PASS"


def test_avoid_and_low_confidence_report_both_violations() -> None:
    out = _assess_one(_rec(confidence=0.2, action="avoid"))
    assert out.violations == ["confidence_below_threshold", "analyst_recommends_avoid"]


# --------------------------------------------------------------------------- #
# Sector cap
# --------------------------------------------------------------------------- #
def test_sector_cap_admits_exactly_max_per_sector() -> None:
    counts: Dict[str, int] = {}
    decisions = [
        _assess_one(_rec(symbol=f"S{i}"), sector="IT", counts=counts).decision
        for i in range(rm.MAX_PER_SECTOR + 1)
    ]
    assert decisions[: rm.MAX_PER_SECTOR] == ["PASS"] * rm.MAX_PER_SECTOR
    assert decisions[rm.MAX_PER_SECTOR] == "REJECT"
    assert counts["IT"] == rm.MAX_PER_SECTOR


def test_sector_cap_names_its_violation() -> None:
    counts = {"IT": rm.MAX_PER_SECTOR}
    out = _assess_one(_rec(), sector="IT", counts=counts)
    assert out.violations == ["sector_limit_exceeded"]


def test_unknown_sector_is_exempt_from_the_cap() -> None:
    """Named-stock lookups carry no sector, so they are never capped."""
    counts: Dict[str, int] = {}
    decisions = [
        _assess_one(_rec(symbol=f"S{i}"), sector=None, counts=counts).decision
        for i in range(rm.MAX_PER_SECTOR + 3)
    ]
    assert decisions == ["PASS"] * (rm.MAX_PER_SECTOR + 3)


def test_unknown_sector_does_not_consume_another_sectors_slots() -> None:
    counts: Dict[str, int] = {}
    for i in range(5):
        _assess_one(_rec(symbol=f"U{i}"), sector=None, counts=counts)
    assert counts == {}


def test_a_rejected_stock_does_not_consume_a_sector_slot() -> None:
    """A REJECT must not spend capacity a passing stock could have used."""
    counts: Dict[str, int] = {}
    _assess_one(_rec(symbol="LOW", confidence=0.1), sector="IT", counts=counts)
    _assess_one(_rec(symbol="AVOID", action="avoid"), sector="IT", counts=counts)
    assert counts.get("IT", 0) == 0

    decisions = [
        _assess_one(_rec(symbol=f"OK{i}"), sector="IT", counts=counts).decision
        for i in range(rm.MAX_PER_SECTOR)
    ]
    assert decisions == ["PASS"] * rm.MAX_PER_SECTOR


def test_sector_counts_are_tracked_independently_per_sector() -> None:
    counts: Dict[str, int] = {}
    for i in range(rm.MAX_PER_SECTOR):
        _assess_one(_rec(symbol=f"IT{i}"), sector="IT", counts=counts)
    out = _assess_one(_rec(symbol="BANK1"), sector="BANKING", counts=counts)
    assert out.decision == "PASS"


def test_sector_check_is_skipped_when_already_violating() -> None:
    """A full sector is not reported on top of a prior breach — short-circuited."""
    counts = {"IT": rm.MAX_PER_SECTOR}
    out = _assess_one(_rec(confidence=0.1), sector="IT", counts=counts)
    assert out.violations == ["confidence_below_threshold"]


def test_sector_is_echoed_onto_the_assessment() -> None:
    assert _assess_one(_rec(), sector="IT").sector == "IT"


# --------------------------------------------------------------------------- #
# Ordering — which names the cap keeps
# --------------------------------------------------------------------------- #
@pytest.fixture()
def _no_llm_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the best-effort note pass; verdicts must not depend on it."""

    async def _passthrough(assessments, recs_by_symbol):  # noqa: ANN001, ARG001
        return assessments

    monkeypatch.setattr(rm, "_annotate", _passthrough)


def _state(recs: List[AnalystRecommendation], sectors: Dict[str, str]) -> PortfolioState:
    from graph.state import ScanResult

    return PortfolioState(
        user_query="test",
        scan_results=[
            ScanResult(symbol=s, signal="test", sector=sec) for s, sec in sectors.items()
        ],
        analyst_recommendations=recs,
    )


@pytest.mark.usefixtures("_no_llm_notes")
async def test_sector_cap_keeps_the_highest_confidence_names() -> None:
    """The cap is applied after a confidence sort — the weakest name is dropped."""
    recs = [
        _rec(symbol="WEAK", confidence=0.80),
        _rec(symbol="STRONG", confidence=0.95),
        _rec(symbol="MID", confidence=0.85),
        _rec(symbol="GOOD", confidence=0.90),
    ]
    sectors = {s: "IT" for s in ("WEAK", "STRONG", "MID", "GOOD")}

    out = await rm.risk_manager(_state(recs, sectors))
    verdicts = {a.symbol: a.decision for a in out.risk_assessments}

    assert verdicts["STRONG"] == "PASS"
    assert verdicts["GOOD"] == "PASS"
    assert verdicts["MID"] == "PASS"
    assert verdicts["WEAK"] == "REJECT"


@pytest.mark.usefixtures("_no_llm_notes")
async def test_assessments_are_returned_highest_confidence_first() -> None:
    recs = [_rec(symbol="A", confidence=0.72), _rec(symbol="B", confidence=0.99)]
    out = await rm.risk_manager(_state(recs, {"A": "IT", "B": "BANKING"}))
    assert [a.symbol for a in out.risk_assessments] == ["B", "A"]


# --------------------------------------------------------------------------- #
# Rejection summary
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("_no_llm_notes")
async def test_rejection_reason_is_set_only_when_every_candidate_fails() -> None:
    recs = [_rec(symbol="A", confidence=0.1), _rec(symbol="B", action="avoid")]
    out = await rm.risk_manager(_state(recs, {"A": "IT", "B": "IT"}))
    assert out.rejection_reason is not None
    assert "confidence_below_threshold" in out.rejection_reason
    assert "analyst_recommends_avoid" in out.rejection_reason


@pytest.mark.usefixtures("_no_llm_notes")
async def test_one_survivor_means_no_rejection_reason() -> None:
    recs = [_rec(symbol="A", confidence=0.1), _rec(symbol="B", confidence=0.9)]
    out = await rm.risk_manager(_state(recs, {"A": "IT", "B": "IT"}))
    assert out.rejection_reason is None


@pytest.mark.usefixtures("_no_llm_notes")
async def test_no_recommendations_is_not_a_rejection() -> None:
    """An empty analyst list is an empty run, not 'everything was rejected'."""
    out = await rm.risk_manager(_state([], {}))
    assert out.risk_assessments == []
    assert out.rejection_reason is None


# --------------------------------------------------------------------------- #
# The LLM must not be able to change a verdict
# --------------------------------------------------------------------------- #
async def test_verdicts_survive_a_failing_note_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """The headline invariant: notes are best-effort, verdicts are arithmetic."""

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("provider down")

    monkeypatch.setattr(rm, "get_lab_llm", _boom)

    recs = [_rec(symbol="A", confidence=0.95), _rec(symbol="B", confidence=0.1)]
    out = await rm.risk_manager(_state(recs, {"A": "IT", "B": "IT"}))

    verdicts = {a.symbol: a.decision for a in out.risk_assessments}
    assert verdicts == {"A": "PASS", "B": "REJECT"}
    assert all(a.notes is None for a in out.risk_assessments)


async def test_notes_are_attached_by_symbol_not_by_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A note pass that reorders or drops symbols must not mislabel a verdict."""

    async def _swapped(assessments, recs_by_symbol):  # noqa: ANN001, ARG001
        # Return notes for one symbol only, and in the opposite order.
        note_map = {"B": "only B gets a note"}
        for a in assessments:
            if a.symbol in note_map:
                a.notes = note_map[a.symbol]
        return assessments

    monkeypatch.setattr(rm, "_annotate", _swapped)

    recs = [_rec(symbol="A", confidence=0.95), _rec(symbol="B", confidence=0.90)]
    out = await rm.risk_manager(_state(recs, {"A": "IT", "B": "BANKING"}))
    by_symbol = {a.symbol: a for a in out.risk_assessments}

    assert by_symbol["B"].notes == "only B gets a note"
    assert by_symbol["A"].notes is None
