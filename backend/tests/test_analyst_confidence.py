"""Analyst confidence plumbing (card B11, phase 2).

These pin the *mapping* — what the analyst node does with the model's output —
not the model's judgement, which is measured separately by
``evals/confidence_probe.py``. The two properties that matter:

1. The new split dimensions (``evidence_quality``, ``data_gaps``) and the
   previously-dropped ``time_horizon`` flow through onto the recommendation.
2. A model that omits the optional fields still parses and still yields a
   recommendation — it is **not** silently dropped. This is the B11 landmine:
   ``_analyze_one`` swallows any exception as ``return None``, so a schema that
   raises on a weaker model would empty out the whole run with nothing logged.
"""

from __future__ import annotations

import logging

import pytest

from agents import analyst as an
from graph.state import ResearchReport


def _report(symbol: str = "RELIANCE") -> ResearchReport:
    return ResearchReport(symbol=symbol, summary="up 2% near 52w high", sources=[])


class _FakeStructured:
    """Stands in for ``structured(llm, _AnalystOutput)`` — returns a fixed output."""

    def __init__(self, output: an._AnalystOutput) -> None:
        self._output = output

    async def ainvoke(self, _prompt):  # noqa: ANN001
        return self._output


def _patch_output(monkeypatch: pytest.MonkeyPatch, output: an._AnalystOutput) -> None:
    monkeypatch.setattr(an, "_get_llm", lambda: object())
    monkeypatch.setattr(an, "structured", lambda _llm, _schema: _FakeStructured(output))


async def test_all_fields_map_onto_the_recommendation(monkeypatch: pytest.MonkeyPatch) -> None:
    out = an._AnalystOutput(
        bull_thesis="bull",
        bear_thesis="bear",
        action="buy",
        confidence=0.82,
        evidence_quality=0.25,
        data_gaps=["earnings", "valuation"],
        key_risks=["macro"],
        catalysts=["results"],
        target_price=3500.0,
        time_horizon="6-12 months",
        thesis="synthesis",
    )
    _patch_output(monkeypatch, out)

    rec = await an._analyze_one(_report())
    assert rec is not None
    assert rec.confidence == 0.82
    assert rec.evidence_quality == 0.25
    assert rec.data_gaps == ["earnings", "valuation"]
    assert rec.time_horizon == "6-12 months"
    assert rec.target_price == 3500.0
    assert rec.action == "buy"


async def test_omitted_optional_fields_do_not_drop_the_stock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The landmine: a model that returns only the required fields must parse."""
    out = an._AnalystOutput(
        bull_thesis="bull",
        bear_thesis="bear",
        action="hold",
        confidence=0.6,
        # evidence_quality, data_gaps, target_price, time_horizon all omitted
    )
    _patch_output(monkeypatch, out)

    rec = await an._analyze_one(_report())
    assert rec is not None  # NOT dropped
    assert rec.evidence_quality is None
    assert rec.data_gaps == []
    assert rec.time_horizon is None


async def test_a_model_failure_is_logged_not_silent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A skipped stock must leave a trace — the empty-run failure mode is silent."""

    class _Boom:
        async def ainvoke(self, _prompt):  # noqa: ANN001
            raise ValueError("model answered in prose, not a tool call")

    monkeypatch.setattr(an, "_get_llm", lambda: object())
    monkeypatch.setattr(an, "structured", lambda _llm, _schema: _Boom())

    with caplog.at_level(logging.WARNING, logger="alphadesk.analyst"):
        rec = await an._analyze_one(_report("FLAKY"))

    assert rec is None
    assert any("FLAKY" in r.message for r in caplog.records)


def test_confidence_precedes_action_in_neither_order_regression() -> None:
    """Reasoning fields come before action/confidence so the number follows the case.

    Pins the deliberate field order (B11): the model fills the argument object
    left to right, so both theses and data_gaps must appear before ``action``,
    which must appear before ``confidence``.
    """
    order = list(an._AnalystOutput.model_fields)
    assert order.index("bull_thesis") < order.index("action")
    assert order.index("bear_thesis") < order.index("action")
    assert order.index("data_gaps") < order.index("action")
    assert order.index("action") < order.index("confidence")
