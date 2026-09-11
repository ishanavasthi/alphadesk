"""RiskManager agent — enforces guardrails on analyst recommendations.

Pure async node ``(state: PortfolioState) -> PortfolioState``. Guardrail
enforcement is deterministic (correctness must not depend on the LLM):

- Min confidence to proceed: ``MIN_CONFIDENCE`` (REJECT below)
- Max stocks per sector: ``MAX_PER_SECTOR``
- Analyst 'avoid' recommendations are rejected

Each recommendation yields a ``RiskAssessment`` with a PASS / REJECT / FLAG
decision. ``openai/gpt-oss-120b`` is used only to attach human-readable risk
notes. If every candidate is rejected, ``state.rejection_reason`` is set.

**Thresholds are model-relative and configurable (B11 phase 3).** ``confidence``
is an LLM self-report of *directional* conviction, and its usable range depends
on the model and on how much evidence the Analyst was handed. The historical
hardcoded 0.70 was set as if the number meant "is this a good pick"; it does not.
Measured against the Lab's actual input — live price and the 52-week range, with
RAG dormant (C1) — every candidate scored below 0.70 on every model tried, so
the run ended before the ``execution`` node and the approval gate was
unreachable. See ``docs/SPECS/B11.md``.

Two consequences are load-bearing:

- The floor is read from the environment, so re-pointing the Lab at another
  model is a config change (``LAB_MIN_CONFIDENCE``), not a code change.
- ``evidence_quality`` **flags, it never rejects.** A hard evidence floor would
  reject the entire book for exactly the reason the confidence floor did — the
  Analyst has thin data by construction until C1 is re-enabled. Thin evidence is
  a reason to make a human look, not a reason to drop the stock silently.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from agents.llm import get_lab_llm, structured
from graph.state import (
    AnalystRecommendation,
    PortfolioState,
    RiskAssessment,
)

# NOTE: the ``openai/`` prefix is part of the *Groq* model id (GPT OSS 120B
# served by Groq) — the default route is Groq, not OpenAI. Override the tier
# with LAB_RISK_MODEL / LAB_MODEL and the route with LAB_PROVIDER.
RISK_MODEL = "openai/gpt-oss-120b"

logger = logging.getLogger("alphadesk.risk")


def _env_float(name: str, default: float) -> float:
    """A threshold from the environment, falling back to the measured default.

    Read at import, which is the deployment model: the Space sets its
    environment before boot. A malformed or out-of-range value is refused
    loudly rather than silently reshaping the gate.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; falling back to %s", name, raw, default)
        return default
    if not 0.0 <= value <= 1.0:
        logger.warning("%s=%s is outside [0, 1]; falling back to %s", name, value, default)
        return default
    return value


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; falling back to %s", name, raw, default)
        return default
    if value < 1:
        logger.warning("%s=%s is not positive; falling back to %s", name, value, default)
        return default
    return value


#: Defaults are **measured**, not chosen — 139 scores across three probe runs on
#: the current Lab analyst model (`openai/gpt-oss-120b`), documented in
#: docs/SPECS/B11.md §6. Observed there: confidence 0.44–0.68 with a mode of
#: exactly 0.55, evidence_quality 0.15–0.30, and — in every run — a rerun spread
#: at temperature 0 *larger than* the spread between six deliberately different
#: setups. Point the Lab at another model and every one of these must be
#: re-measured, which is why each is overridable from the environment.

#: **A collapse detector, not a quality bar.** Set below the lowest confidence
#: ever observed (0.44), so a legitimate score never rejects on this alone. That
#: is deliberate: the number cannot separate good stocks from bad ones (its
#: between-stock spread sits at or under its own decoding noise), so using it to
#: drop candidates rejected the entire book — the bug B11 was opened for. What it
#: still catches is a model that has genuinely broken and is emitting 0.05.
DEFAULT_MIN_CONFIDENCE = 0.40

#: Set above the highest confidence ever observed (0.68), so **every**
#: recommendation from the current model is a FLAG rather than a clean PASS.
#: Also deliberate, and also honest: on price-and-52-week-range input alone there
#: is no such thing as a high-conviction call here, and a PASS badge would claim
#: a confidence the measurement does not support. A model with real spread earns
#: PASS back by moving LAB_FLAG_BAND.
DEFAULT_FLAG_BAND = 0.70

#: Above the highest evidence_quality observed (0.30), so `thin_evidence` fires
#: on essentially every recommendation while RAG is dormant (C1) and the Analyst
#: sees five price fields. That is the true state of the data. It is a standing
#: caution rather than a per-stock discriminator, and it stops firing on its own
#: once C1 gives the Analyst something to read.
DEFAULT_MIN_EVIDENCE = 0.35

#: Below this, REJECT.
MIN_CONFIDENCE = _env_float("LAB_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
#: Clears the guardrails but is flagged for review below this.
_FLAG_BAND = _env_float("LAB_FLAG_BAND", DEFAULT_FLAG_BAND)
#: Below this, FLAG (never REJECT) — see the module docstring.
MIN_EVIDENCE = _env_float("LAB_MIN_EVIDENCE", DEFAULT_MIN_EVIDENCE)
MAX_PER_SECTOR = _env_int("LAB_MAX_PER_SECTOR", 3)


class _RiskNote(BaseModel):
    symbol: str
    note: str


class _RiskNotes(BaseModel):
    notes: List[_RiskNote] = Field(default_factory=list)


def _sector_map(state: PortfolioState) -> Dict[str, Optional[str]]:
    return {s.symbol: s.sector for s in state.scan_results}


def _assess(
    rec: AnalystRecommendation,
    sector: Optional[str],
    sector_counts: Dict[str, int],
) -> RiskAssessment:
    violations: List[str] = []
    if rec.confidence < MIN_CONFIDENCE:
        violations.append("confidence_below_threshold")
    if rec.action == "avoid":
        violations.append("analyst_recommends_avoid")

    # Sector cap only applies to known sectors. Named-stock lookups carry no
    # sector, so they are never blocked by (or counted toward) the cap.
    if not violations and sector and sector_counts.get(sector, 0) >= MAX_PER_SECTOR:
        violations.append("sector_limit_exceeded")

    approved = not violations
    flags: List[str] = []
    if approved:
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if rec.confidence < _FLAG_BAND:
            flags.append("borderline_confidence")
        # Evidence flags but never rejects. The Analyst is handed price and the
        # 52-week range and nothing else (RAG dormant, C1), so an evidence floor
        # that could REJECT would empty the book exactly the way the old 0.70
        # confidence floor did. ``None`` means the model omitted the field —
        # absence of a self-report is not evidence of thin data, so it is not
        # flagged.
        if rec.evidence_quality is not None and rec.evidence_quality < MIN_EVIDENCE:
            flags.append("thin_evidence")
        decision = "FLAG" if flags else "PASS"
    else:
        decision = "REJECT"

    return RiskAssessment(
        symbol=rec.symbol,
        sector=sector,
        approved=approved,
        decision=decision,
        confidence=rec.confidence,
        evidence_quality=rec.evidence_quality,
        violations=violations,
        flags=flags,
    )


async def _annotate(
    assessments: List[RiskAssessment],
    recs_by_symbol: Dict[str, AnalystRecommendation],
) -> List[RiskAssessment]:
    """Attach one-line LLM risk notes (best-effort; deterministic verdicts unchanged)."""
    if not assessments:
        return assessments
    lines = [
        "You are a risk manager for an equity research desk.",
        "For each assessment write a one-line note explaining the verdict.",
        f"Guardrails: min confidence {MIN_CONFIDENCE}, max {MAX_PER_SECTOR} stocks per sector.",
        "A 'flag' is a caution, not a breach: the stock still clears the guardrails.",
        "evidence_quality is how thin the underlying data was, not how good the stock is.",
        "",
        "Assessments:",
    ]
    for a in assessments:
        rec = recs_by_symbol.get(a.symbol)
        lines.append(
            f"- {a.symbol} sector={a.sector} decision={a.decision} "
            f"confidence={a.confidence} evidence_quality={a.evidence_quality} "
            f"violations={a.violations} flags={a.flags} "
            f"action={getattr(rec, 'action', None)}"
        )
    try:
        llm = structured(get_lab_llm("risk", RISK_MODEL, temperature=0), _RiskNotes)
        out = await llm.ainvoke("\n".join(lines))
        note_map = {n.symbol: n.note for n in out.notes}
        for a in assessments:
            if a.symbol in note_map:
                a.notes = note_map[a.symbol]
    except Exception:  # noqa: BLE001 - notes are optional
        pass
    return assessments


def _summarize_rejection(assessments: List[RiskAssessment]) -> str:
    reasons = sorted({v for a in assessments for v in a.violations})
    symbols = ", ".join(a.symbol for a in assessments)
    summary = (
        f"All {len(assessments)} candidate(s) rejected ({symbols}). "
        f"Violations: {', '.join(reasons) or 'n/a'}."
    )
    # The signature of a mis-set gate rather than a genuinely bad book: nothing
    # failed for a *reason* — no 'avoid', no full sector — every candidate just
    # scored under the floor. That is what B11 phase 0 found, and with no
    # diagnostic it read from the UI as "the desk rejects everything".
    if reasons == ["confidence_below_threshold"]:
        best = max((a.confidence for a in assessments), default=0.0)
        summary += (
            f" Every candidate failed on confidence alone (best {best:.2f} against a "
            f"{MIN_CONFIDENCE:.2f} floor) — no analyst 'avoid', no sector at its cap. "
            "If that repeats across runs the floor is probably mis-set for the current "
            "Lab analyst model: re-measure with `python -m evals.confidence_probe` and "
            "set LAB_MIN_CONFIDENCE."
        )
    return summary


async def risk_manager(state: PortfolioState) -> PortfolioState:
    """Populate ``state.risk_assessments`` and ``state.rejection_reason`` if all fail."""
    sectors = _sector_map(state)
    # Highest-confidence first so the sector cap keeps the strongest names.
    ordered = sorted(
        state.analyst_recommendations, key=lambda r: r.confidence, reverse=True
    )
    sector_counts: Dict[str, int] = {}
    assessments = [_assess(rec, sectors.get(rec.symbol), sector_counts) for rec in ordered]

    assessments = await _annotate(assessments, {r.symbol: r for r in ordered})
    state.risk_assessments = assessments

    if assessments and all(not a.approved for a in assessments):
        state.rejection_reason = _summarize_rejection(assessments)
    return state
