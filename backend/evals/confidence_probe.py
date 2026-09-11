"""B11 phase 0 — measure what the Analyst's ``confidence`` number actually is.

`AnalystRecommendation.confidence` drives all three risk verdicts, sorts the
sector cap, and renders as a filled bar in the UI, but nothing in the prompt
defines it: the model is asked for ``confidence (0-1)`` and the schema says
``Confidence 0-1.``. This script measures the number before B11 changes it.

**Not a pytest test on purpose.** `tests/conftest.py` scrubs every provider key
from the environment (issue #31), so a probe that needs a real key cannot live
there. Run it explicitly:

    cd backend
    ../.venv/bin/python -m evals.confidence_probe --runs 3
    ../.venv/bin/python -m evals.confidence_probe --provider groq --model openai/gpt-oss-120b

It calls the **real** Analyst path — `analyst._build_prompt` and the same
`structured()` binding — so what it measures is what the Lab ships, minus the
`except: return None` that would otherwise hide a failure.

### The design

Histogramming confidences answers "what values appear" but not the question that
decides whether B11 phases 2-4 are worth doing: *does the number carry
information?* So the fixture set is built to separate signal from noise:

- **A contrast set** — six setups a competent analyst should feel measurably
  different about (clean momentum, falling knife, no data, contradictory
  signals, flat mid-cap, thin micro-cap).
- **A twin pair** — `TWINA`/`TWINB`, byte-identical research differing only in
  ticker. Any gap between them is pure noise, since there is nothing to be
  differentially confident about.
- **Repeats** — every report scored `--runs` times at `temperature=0`, which is
  what the Lab uses, so rerun spread is decoding nondeterminism.

The comparison that matters is **between-stock spread vs. twin gap**. If the
contrast set spreads no wider than the twins, the number is noise wearing a
bar chart, and the honest fix is to stop drawing it — not to tune thresholds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

# The probe is useless without a real key, so unlike the test suite it *wants*
# backend/.env. Loaded before agents.llm reads the environment.
load_dotenv()

from agents import analyst as an  # noqa: E402
from agents.llm import lab_model, lab_provider, structured  # noqa: E402
from graph.state import ResearchReport  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures — shaped exactly like what agents/research.py emits
# --------------------------------------------------------------------------- #
# The Research agent writes a 2-3 sentence factual summary and a `fundamentals`
# dict of at most five price-derived keys (live_price, day_change_percentage,
# market_cap_cr, week52_high, week52_low). Nothing else reaches the Analyst:
# RAG is dormant (C1), so `citations` is always []. These mirror that exactly.

_REPORTS: List[ResearchReport] = [
    ResearchReport(
        symbol="CLEANMOM",
        summary=(
            "The stock is trading at 3421.50, up 2.10% on the day, and sits near the "
            "top of its 52-week range of 1980.00-3480.00. Market capitalisation is "
            "approximately 304000 crore, placing it among large-cap names."
        ),
        fundamentals={
            "live_price": 3421.5,
            "day_change_percentage": 2.1,
            "market_cap_cr": 304000.0,
            "week52_high": 3480.0,
            "week52_low": 1980.0,
        },
        sources=["get_indian_stocks_details"],
    ),
    ResearchReport(
        symbol="KNIFE",
        summary=(
            "The stock is trading at 214.30, down 7.80% on the day, and is close to "
            "its 52-week low of 208.00 against a 52-week high of 890.00. Market "
            "capitalisation is approximately 4100 crore."
        ),
        fundamentals={
            "live_price": 214.3,
            "day_change_percentage": -7.8,
            "market_cap_cr": 4100.0,
            "week52_high": 890.0,
            "week52_low": 208.0,
        },
        sources=["get_indian_stocks_details"],
    ),
    ResearchReport(
        symbol="NODATA",
        summary="The stock is trading at 655.00. No further details were available.",
        fundamentals={"live_price": 655.0},
        sources=["get_indian_stocks_details"],
    ),
    ResearchReport(
        symbol="MIXED",
        summary=(
            "The stock is trading at 1780.00, down 4.20% on the day, yet remains near "
            "its 52-week high of 1840.00 against a 52-week low of 720.00. Market "
            "capitalisation is approximately 52000 crore."
        ),
        fundamentals={
            "live_price": 1780.0,
            "day_change_percentage": -4.2,
            "market_cap_cr": 52000.0,
            "week52_high": 1840.0,
            "week52_low": 720.0,
        },
        sources=["get_indian_stocks_details"],
    ),
    ResearchReport(
        symbol="FLATMID",
        summary=(
            "The stock is trading at 1140.00, up 0.10% on the day, near the midpoint "
            "of its 52-week range of 890.00-1390.00. Market capitalisation is "
            "approximately 21000 crore."
        ),
        fundamentals={
            "live_price": 1140.0,
            "day_change_percentage": 0.1,
            "market_cap_cr": 21000.0,
            "week52_high": 1390.0,
            "week52_low": 890.0,
        },
        sources=["get_indian_stocks_details"],
    ),
    ResearchReport(
        symbol="MICROVOL",
        summary=(
            "The stock is trading at 47.85, up 19.60% on the day, against a 52-week "
            "range of 22.10-51.00. Market capitalisation is approximately 310 crore, "
            "placing it in the micro-cap band."
        ),
        fundamentals={
            "live_price": 47.85,
            "day_change_percentage": 19.6,
            "market_cap_cr": 310.0,
            "week52_high": 51.0,
            "week52_low": 22.1,
        },
        sources=["get_indian_stocks_details"],
    ),
]

#: The noise probe. Identical research, different ticker — any gap between the
#: two confidences is decoding noise plus whatever the ticker string itself
#: evokes, because there is no information distinguishing them.
_TWIN_SUMMARY = (
    "The stock is trading at 962.40, up 1.30% on the day, within a 52-week range "
    "of 610.00-1105.00. Market capitalisation is approximately 38000 crore."
)
_TWIN_FUNDAMENTALS = {
    "live_price": 962.4,
    "day_change_percentage": 1.3,
    "market_cap_cr": 38000.0,
    "week52_high": 1105.0,
    "week52_low": 610.0,
}
_TWINS: List[ResearchReport] = [
    ResearchReport(
        symbol=sym,
        summary=_TWIN_SUMMARY,
        fundamentals=dict(_TWIN_FUNDAMENTALS),
        sources=["get_indian_stocks_details"],
    )
    for sym in ("TWINA", "TWINB")
]


# --------------------------------------------------------------------------- #
# Probe
# --------------------------------------------------------------------------- #
@dataclass
class _Observations:
    symbol: str
    confidences: List[float] = field(default_factory=list)
    evidence: List[float] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)

    @property
    def evidence_mean(self) -> Optional[float]:
        return statistics.fmean(self.evidence) if self.evidence else None

    @property
    def mean(self) -> Optional[float]:
        return statistics.fmean(self.confidences) if self.confidences else None

    @property
    def spread(self) -> Optional[float]:
        if len(self.confidences) < 2:
            return 0.0 if self.confidences else None
        return max(self.confidences) - min(self.confidences)


#: Per-call ceiling. A provider can hang a single request indefinitely (observed
#: on B.ai glm-5.3-flash under the longer B11 prompt), and neither the probe nor
#: the Lab has an intrinsic timeout — so bound it here and record the hang as a
#: failure rather than stalling the whole probe on one call.
_CALL_TIMEOUT_S = 90.0


async def _score_once(report: ResearchReport):
    """One real Analyst call. Mirrors ``analyst._analyze_one`` without its except."""
    prompt = an._build_prompt(report, context=[])  # RAG is dormant: always []
    try:
        llm = structured(an._get_llm(), an._AnalystOutput)
        out = await asyncio.wait_for(llm.ainvoke(prompt), timeout=_CALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        return None, None, None, f"timeout>{_CALL_TIMEOUT_S:.0f}s"
    except Exception as exc:  # noqa: BLE001 - the probe reports what the Lab hides
        return None, None, None, f"{type(exc).__name__}: {exc}"[:200]
    return out.confidence, out.evidence_quality, out.action, None


async def _probe(reports: List[ResearchReport], runs: int, pace: float) -> Dict[str, _Observations]:
    results = {r.symbol: _Observations(symbol=r.symbol) for r in reports}
    total = len(reports) * runs
    done = 0
    for _ in range(runs):
        for report in reports:
            conf, evidence, action, err = await _score_once(report)
            obs = results[report.symbol]
            if err is not None:
                obs.failures.append(err)
            else:
                obs.confidences.append(float(conf))
                if evidence is not None:
                    obs.evidence.append(float(evidence))
                obs.actions.append(str(action))
            done += 1
            print(f"\r  scored {done}/{total}", end="", file=sys.stderr, flush=True)
            if pace:
                await asyncio.sleep(pace)
    print("", file=sys.stderr)
    return results


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
_MIN_CONFIDENCE = 0.70
_FLAG_BAND = 0.75


def _band(value: float) -> str:
    if value < _MIN_CONFIDENCE:
        return "REJECT"
    return "FLAG" if value < _FLAG_BAND else "PASS"


def _render(
    contrast: Dict[str, _Observations],
    twins: Dict[str, _Observations],
    *,
    provider: str,
    model: str,
    runs: int,
) -> dict:
    print()
    print(f"  provider={provider}  model={model}  runs={runs}  temperature=0")
    print()
    print(f"  {'symbol':<10} {'n':>2}  {'conf':>6} {'min':>6} {'max':>6} {'rerun Δ':>8} {'evid':>6}  {'band':<7} actions")
    print(f"  {'-' * 10} {'-' * 2}  {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 8} {'-' * 6}  {'-' * 7} {'-' * 20}")

    def _row(obs: _Observations) -> None:
        if not obs.confidences:
            print(f"  {obs.symbol:<10} {'0':>2}  {'—':>6} {'—':>6} {'—':>6} {'—':>8} {'—':>6}  {'FAIL':<7} {obs.failures[0][:40] if obs.failures else ''}")
            return
        acts = ",".join(sorted(set(obs.actions)))
        evid = f"{obs.evidence_mean:.3f}" if obs.evidence_mean is not None else "—"
        print(
            f"  {obs.symbol:<10} {len(obs.confidences):>2}  "
            f"{obs.mean:>6.3f} {min(obs.confidences):>6.3f} {max(obs.confidences):>6.3f} "
            f"{obs.spread:>8.3f} {evid:>6}  {_band(obs.mean):<7} {acts}"
        )

    for obs in contrast.values():
        _row(obs)
    print(f"  {'-' * 10}")
    for obs in twins.values():
        _row(obs)
    print()

    # ---- the two numbers the phase-0 gate turns on ----
    means = [o.mean for o in contrast.values() if o.mean is not None]
    twin_means = [o.mean for o in twins.values() if o.mean is not None]
    all_conf = [c for o in contrast.values() for c in o.confidences]

    between = (max(means) - min(means)) if len(means) >= 2 else None
    twin_gap = abs(twin_means[0] - twin_means[1]) if len(twin_means) == 2 else None
    rerun = statistics.fmean([o.spread for o in contrast.values() if o.spread is not None]) or 0.0
    bands = {b: sum(1 for c in all_conf if _band(c) == b) for b in ("REJECT", "FLAG", "PASS")}

    print("  Signal vs noise")
    print(f"    between-stock spread (6 different setups) : {_fmt(between)}")
    print(f"    twin gap (identical research, diff ticker): {_fmt(twin_gap)}")
    print(f"    mean rerun spread at temperature=0        : {_fmt(rerun)}")
    print()
    print("  Threshold discrimination")
    print(f"    distinct values observed : {len(set(all_conf))} of {len(all_conf)} scores")
    print(f"    band occupancy           : {bands}")
    failures = sum(len(o.failures) for o in {**contrast, **twins}.values())
    print(f"    structured-output failures: {failures}")
    print()

    verdict = _verdict(between, twin_gap, bands)
    print(f"  VERDICT: {verdict}")
    print()

    return {
        "provider": provider,
        "model": model,
        "runs": runs,
        "between_stock_spread": between,
        "twin_gap": twin_gap,
        "mean_rerun_spread": rerun,
        "distinct_values": len(set(all_conf)),
        "total_scores": len(all_conf),
        "band_occupancy": bands,
        "failures": failures,
        "verdict": verdict,
        "per_symbol": {
            s: {
                "mean": o.mean,
                "min": min(o.confidences) if o.confidences else None,
                "max": max(o.confidences) if o.confidences else None,
                "confidences": o.confidences,
                "evidence_quality": o.evidence,
                "evidence_mean": o.evidence_mean,
                "actions": o.actions,
                "failures": o.failures,
            }
            for s, o in {**contrast, **twins}.items()
        },
    }


def _fmt(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.3f}"


def _verdict(between: Optional[float], twin_gap: Optional[float], bands: Dict[str, int]) -> str:
    """The phase-0 gate, stated as code so it is not argued after the fact."""
    if between is None:
        return "INCONCLUSIVE — no scores returned"
    if between < 0.05:
        return (
            "DEGENERATE — the number does not discriminate between setups. "
            "Phase 4 (stop drawing it as a bar) is the honest fix; skip 2-3."
        )
    if twin_gap is not None and twin_gap >= between:
        return (
            "NOISE-DOMINATED — identical research moves the number as much as "
            "genuinely different setups do. Phase 4 first; 2-3 only if it survives."
        )
    occupied = sum(1 for count in bands.values() if count)
    if occupied == 1:
        return (
            "SINGLE-BAND — every score lands in one verdict band, so the 0.70/0.75 "
            "thresholds separate nothing. Phase 3 (model-relative thresholds) is required."
        )
    return "DISCRIMINATING — the number carries signal. Phases 2-4 as planned."


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3, help="scores per report (default 3)")
    parser.add_argument("--provider", help="override LAB_PROVIDER for this probe")
    parser.add_argument("--model", help="override LAB_ANALYST_MODEL for this probe")
    parser.add_argument("--pace", type=float, default=0.4, help="seconds between calls")
    parser.add_argument("--timeout", type=float, help="per-call timeout in seconds")
    parser.add_argument("--json", type=Path, help="also write the raw results here")
    args = parser.parse_args()

    if args.provider:
        os.environ["LAB_PROVIDER"] = args.provider
    if args.model:
        os.environ["LAB_ANALYST_MODEL"] = args.model
    if args.timeout:
        global _CALL_TIMEOUT_S
        _CALL_TIMEOUT_S = args.timeout

    provider = lab_provider() or "(env default)"
    model = lab_model("analyst", an.ANALYST_MODEL)

    async def _run_both():
        # One event loop for both passes: the provider's async HTTP client binds
        # to the loop that created it, so a second asyncio.run() tears down the
        # first loop underneath it and raises "Event loop is closed" on exit.
        return (
            await _probe(_REPORTS, args.runs, args.pace),
            await _probe(_TWINS, args.runs, args.pace),
        )

    contrast, twins = asyncio.run(_run_both())
    payload = _render(contrast, twins, provider=str(provider), model=model, runs=args.runs)

    if args.json:
        args.json.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"  wrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
