"""RiskManager guardrails (card B11, phase 1) — the deterministic core, pinned.

``CLAUDE.md`` advertises one property above all others for this agent:
*"Guardrail enforcement is deterministic (correctness must not depend on the
LLM)."* Until this file existed nothing tested it — ``MIN_CONFIDENCE``,
``_FLAG_BAND`` and ``MAX_PER_SECTOR`` appeared in no test in the suite, so every
threshold boundary and the sector cap's tie-breaking were free to move silently.

Each boundary is tested on both sides (0.399/0.40, 0.6999/0.70) because an
off-by-one in a comparison operator is exactly the mutation a coarser test
would miss.

The literal values are the **measured** phase-3 defaults (docs/SPECS/B11.md §6),
not arbitrary ones, and they are pinned as literals on purpose: a threshold that
drifts silently is the failure this card exists to fix, so a change to any of
them must break a test and be argued for. The env-override mechanism that lets an
operator retune them without touching source is covered separately below.
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
    evidence_quality: Optional[float] = 1.0,
) -> AnalystRecommendation:
    """A recommendation that clears every guardrail unless a field is overridden.

    ``evidence_quality`` defaults to 1.0 rather than ``None`` so the baseline
    recommendation is a clean PASS: the fixture's job is to isolate whichever
    field a test overrides.
    """
    return AnalystRecommendation(
        symbol=symbol,
        action=action,
        confidence=confidence,
        evidence_quality=evidence_quality,
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
        (0.39, "REJECT", False),
        (0.3999, "REJECT", False),
        (0.40, "FLAG", True),  # MIN_CONFIDENCE is inclusive: >= 0.40 proceeds
        (0.55, "FLAG", True),  # the current model's modal score
        (0.6999, "FLAG", True),
        (0.70, "PASS", True),  # _FLAG_BAND is exclusive: >= 0.70 is a clean PASS
        (1.0, "PASS", True),
    ],
)
def test_confidence_boundaries(confidence: float, decision: str, approved: bool) -> None:
    out = _assess_one(_rec(confidence=confidence))
    assert out.decision == decision
    assert out.approved is approved


def test_below_threshold_names_the_violation() -> None:
    # 0.20 is below anything the current model has been observed to emit
    # (measured floor 0.44), i.e. the collapsed-model case the floor now exists
    # to catch — see the MIN_CONFIDENCE comment in risk_manager.
    out = _assess_one(_rec(confidence=0.20))
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


# --------------------------------------------------------------------------- #
# Evidence quality — flags, never rejects (B11 phase 3)
# --------------------------------------------------------------------------- #
# The whole point of the phase-3 change: `confidence` measured how sure the model
# felt, and a 0.70 floor on it emptied the book. `evidence_quality` measures how
# thin the data was — which on this desk is *always* thin (price + 52-week range,
# RAG dormant). So it must be able to caution and must never be able to block, or
# the same bug reappears wearing a different field name.
def test_thin_evidence_flags_but_does_not_reject() -> None:
    out = _assess_one(_rec(confidence=0.99, evidence_quality=0.0))
    assert out.decision == "FLAG"
    assert out.approved is True
    assert out.violations == []
    assert "thin_evidence" in out.flags


def test_thin_evidence_is_never_a_violation_at_any_value() -> None:
    """No evidence value may put a symbol in `violations` — that would REJECT it."""
    for evidence in (0.0, 0.01, 0.1, 0.25, 0.5, 1.0):
        out = _assess_one(_rec(confidence=0.99, evidence_quality=evidence))
        assert out.violations == [], f"evidence_quality={evidence} produced a violation"
        assert out.approved is True


@pytest.mark.parametrize(
    ("evidence", "flagged"),
    [
        (0.0, True),
        (rm.MIN_EVIDENCE - 0.01, True),
        (rm.MIN_EVIDENCE, False),  # the floor is inclusive: at it, not below it
        (rm.MIN_EVIDENCE + 0.01, False),
        (1.0, False),
    ],
)
def test_evidence_floor_boundary(evidence: float, flagged: bool) -> None:
    out = _assess_one(_rec(confidence=0.99, evidence_quality=evidence))
    assert ("thin_evidence" in out.flags) is flagged
    assert out.decision == ("FLAG" if flagged else "PASS")


def test_missing_evidence_is_not_treated_as_thin() -> None:
    """`None` means the model omitted the field, not that the data was bad.

    Older runs and weaker models leave it unset; inferring "thin" from silence
    would flag every one of them for a reason that was never measured.
    """
    out = _assess_one(_rec(confidence=0.99, evidence_quality=None))
    assert out.flags == []
    assert out.decision == "PASS"
    assert out.evidence_quality is None


def test_evidence_quality_is_echoed_onto_the_assessment() -> None:
    out = _assess_one(_rec(confidence=0.99, evidence_quality=0.42))
    assert out.evidence_quality == 0.42


# --------------------------------------------------------------------------- #
# Flags — the reason a FLAG is a FLAG
# --------------------------------------------------------------------------- #
def test_borderline_confidence_is_named_as_a_flag() -> None:
    out = _assess_one(_rec(confidence=rm.MIN_CONFIDENCE))
    assert out.decision == "FLAG"
    assert "borderline_confidence" in out.flags


def test_both_cautions_can_apply_at_once() -> None:
    out = _assess_one(_rec(confidence=rm.MIN_CONFIDENCE, evidence_quality=0.0))
    assert out.decision == "FLAG"
    assert set(out.flags) == {"borderline_confidence", "thin_evidence"}


def test_a_clean_pass_carries_no_flags() -> None:
    out = _assess_one(_rec(confidence=1.0, evidence_quality=1.0))
    assert out.decision == "PASS"
    assert out.flags == []


def test_a_rejected_stock_is_not_also_flagged() -> None:
    """Flags describe approvable stock. A REJECT has violations, not cautions."""
    out = _assess_one(_rec(confidence=0.0, evidence_quality=0.0))
    assert out.decision == "REJECT"
    assert out.flags == []
    assert out.violations == ["confidence_below_threshold"]


# --------------------------------------------------------------------------- #
# Thresholds come from the environment
# --------------------------------------------------------------------------- #
def test_env_float_accepts_a_valid_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_MIN_CONFIDENCE", "0.42")
    assert rm._env_float("LAB_MIN_CONFIDENCE", 0.55) == 0.42


@pytest.mark.parametrize("raw", ["", "   ", "abc", "1.5", "-0.1", "nan-ish"])
def test_env_float_falls_back_on_junk(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed threshold must not silently reshape the gate."""
    monkeypatch.setenv("LAB_MIN_CONFIDENCE", raw)
    assert rm._env_float("LAB_MIN_CONFIDENCE", 0.55) == 0.55


def test_env_float_is_unset_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAB_MIN_CONFIDENCE", raising=False)
    assert rm._env_float("LAB_MIN_CONFIDENCE", 0.55) == 0.55


def test_env_int_accepts_a_valid_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_MAX_PER_SECTOR", "5")
    assert rm._env_int("LAB_MAX_PER_SECTOR", 3) == 5


@pytest.mark.parametrize("raw", ["", "abc", "0", "-2", "2.5"])
def test_env_int_falls_back_on_junk(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_MAX_PER_SECTOR", raw)
    assert rm._env_int("LAB_MAX_PER_SECTOR", 3) == 3


def test_the_bands_are_ordered() -> None:
    """REJECT below MIN_CONFIDENCE, FLAG up to _FLAG_BAND, PASS above.

    A config that inverts these would make the FLAG band unreachable and every
    cleared stock a silent PASS.
    """
    assert 0.0 <= rm.MIN_CONFIDENCE <= rm._FLAG_BAND <= 1.0
    assert 0.0 <= rm.MIN_EVIDENCE <= 1.0


# --------------------------------------------------------------------------- #
# The rejection diagnostic
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("_no_llm_notes")
async def test_an_all_confidence_wipeout_says_the_gate_may_be_mis_set() -> None:
    """The B11 phase-0 failure, made legible.

    When nothing failed for a *reason* — no 'avoid', no full sector — and the
    entire book just scored under the floor, that is the signature of a
    threshold mis-set for the current model, not of a bad set of candidates.
    Without this the UI said only "rejected", which is what sent the operator
    looking for a bug in the analyst.
    """
    recs = [
        _rec(symbol="A", confidence=rm.MIN_CONFIDENCE - 0.10),
        _rec(symbol="B", confidence=rm.MIN_CONFIDENCE - 0.05),
    ]
    out = await rm.risk_manager(_state(recs, {"A": "IT", "B": "BANKING"}))

    assert out.rejection_reason is not None
    assert "confidence alone" in out.rejection_reason
    assert "LAB_MIN_CONFIDENCE" in out.rejection_reason
    # It quotes the best score seen against the floor, so the size of the
    # mismatch is visible without re-running anything.
    assert f"{rm.MIN_CONFIDENCE - 0.05:.2f}" in out.rejection_reason


@pytest.mark.usefixtures("_no_llm_notes")
async def test_a_mixed_wipeout_does_not_blame_the_threshold() -> None:
    """One 'avoid' means the book really was rejected on its merits."""
    recs = [
        _rec(symbol="A", confidence=rm.MIN_CONFIDENCE - 0.10),
        _rec(symbol="B", action="avoid"),
    ]
    out = await rm.risk_manager(_state(recs, {"A": "IT", "B": "BANKING"}))

    assert out.rejection_reason is not None
    assert "confidence alone" not in out.rejection_reason
    assert "LAB_MIN_CONFIDENCE" not in out.rejection_reason
