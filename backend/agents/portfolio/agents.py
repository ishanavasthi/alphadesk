"""The overview specialists and the synthesizer (card A1, item 3/5/8).

Four parallel specialists each read the **verified metrics** and write a short
finding; a synthesizer weaves them into the narrative. Every LLM call goes
through OpenAI explicitly (``provider="openai"``) and every prompt is routed
through :func:`redact`.

The agents never do arithmetic. They are handed the metric catalog — label,
computed ``display``, and short ``detail`` — and are told to cite any figure by
writing a ``[[metric_key]]`` token, never a numeral. ``narrative.parse_prose``
then substitutes the Python-computed value for each token, so a number can only
ever come from :mod:`agents.portfolio.metrics`.

**Descriptive only** (§8.3): the prompts forbid forward projections and any
instrument-level buy/sell call on real holdings. The system line says so and the
synthesizer is reminded again.
"""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from agents.llm import get_chat_llm
from agents.portfolio.metrics import Metric
from agents.portfolio.redact import redact

#: The OpenAI model the overview runs on. Cheap by default; override per deploy.
OVERVIEW_MODEL = os.environ.get("OPENAI_OVERVIEW_MODEL", "").strip() or "gpt-4o-mini"

#: Per-request timeout (seconds). A *stalled* provider connection would otherwise
#: hold the SSE stream open near the server's ~600s ceiling; this makes a hung
#: call degrade to "AI overview unavailable" promptly. (An immediate connection
#: error already degrades fine.) Override with OPENAI_OVERVIEW_TIMEOUT.
def _overview_timeout() -> float:
    raw = (os.environ.get("OPENAI_OVERVIEW_TIMEOUT") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return 30.0
    return value if value > 0 else 30.0

#: The specialist roster, in fan-out order. Each names the metric keys it may
#: cite and the angle it reasons about. ``sip_health`` leans on the SIP roster
#: and the cash/equity split; it says little when there is nothing to say.
SPECIALISTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "allocation_critic",
        "how the portfolio is spread across asset types and how much sits in equity",
        ("equity_share", "us_exposure_share", "current_value", "holdings_count"),
    ),
    (
        "concentration_risk",
        "how concentrated the book is — single-name and top-few dominance",
        ("herfindahl_index", "top_holding_weight", "top_holding_name", "top3_weight"),
    ),
    (
        "sip_health",
        "the systematic-investment roster and the balance of active contributions",
        ("sip_count", "sip_monthly_total", "equity_share"),
    ),
    (
        "performance_attribution",
        "realized return and sector tilt, and what is excluded for lack of a cost basis",
        (
            "pnl",
            "pnl_pct",
            "heaviest_sector_weight",
            "heaviest_sector_name",
            "sector_hhi",
            "rows_without_cost_basis",
            "wow_networth_delta",
            "wow_networth_delta_pct",
        ),
    ),
)

_SYSTEM = (
    "You are a portfolio analyst writing a plain, factual overview of an "
    "investor's current holdings. STRICT RULES: (1) Every figure is precomputed "
    "and given to you; cite a figure ONLY by writing its token like "
    "[[metric_key]] and NEVER type a number, percent, or rupee amount yourself "
    "— spell small counts as words (one, two, three). (2) Describe only what IS "
    "true now. No predictions, no forecasts, no targets, no buy/sell/hold advice "
    "on any holding. (3) Only cite tokens from the provided list; if a value is "
    "not provided, do not mention that number. Keep it concise and neutral."
)

LLMFactory = Callable[[], Any]


class OverviewLLMError(RuntimeError):
    """The overview LLM was unavailable or failed — degrade, do not 500."""


def default_llm_factory() -> Any:
    """Construct the overview chat model on real OpenAI (provider wins over env)."""
    return get_chat_llm(
        OVERVIEW_MODEL, temperature=0.2, provider="openai", timeout=_overview_timeout()
    )


def _catalog(metrics: Mapping[str, Metric], keys: Sequence[str]) -> list[dict[str, Any]]:
    """A redacted, prompt-ready view of the metrics a specialist may cite."""
    rows: list[dict[str, Any]] = []
    for key in keys:
        metric = metrics.get(key)
        if metric is None or not metric.available:
            continue
        rows.append(
            {
                "cite": f"[[{metric.key}]]",
                "label": metric.label,
                "value": metric.display,
                "note": metric.detail,
            }
        )
    return redact(rows)


def _render_catalog(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for row in rows:
        note = f" ({row['note']})" if row.get("note") else ""
        lines.append(f"- {row['cite']} {row['label']}: {row['value']}{note}")
    return "\n".join(lines) if lines else "(no figures available)"


async def _ainvoke(llm: Any, system: str, user: str) -> str:
    try:
        message = await llm.ainvoke([("system", system), ("human", user)])
    except Exception as exc:  # noqa: BLE001 - any failure degrades to unavailable
        raise OverviewLLMError(str(exc)) from exc
    content = getattr(message, "content", None)
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    if not isinstance(content, str) or not content.strip():
        raise OverviewLLMError("empty response from overview model")
    return content.strip()


async def run_specialist(
    name: str,
    focus: str,
    keys: Sequence[str],
    metrics: Mapping[str, Metric],
    llm: Any,
) -> str:
    rows = _catalog(metrics, keys)
    if not rows:
        # Nothing verified to say on this angle — return an empty finding rather
        # than inviting the model to fill the gap.
        return ""
    user = (
        f"You are the '{name}' specialist. Focus: {focus}.\n\n"
        "Available figures (cite by token, never type a number):\n"
        f"{_render_catalog(rows)}\n\n"
        "Write ONE or TWO factual sentences on your focus, embedding the tokens "
        "for any figures you mention. Do not add numbers that are not above."
    )
    return await _ainvoke(llm, _SYSTEM, user)


async def run_synthesizer(
    findings: Mapping[str, str],
    metrics: Mapping[str, Metric],
    llm: Any,
) -> str:
    available = [m for m in metrics.values() if m.available and m.unit != "text"]
    # Route the synthesizer catalog through redact() too — the same gate the
    # specialist path uses. Metrics are clean by construction today, but "every
    # prompt is routed through redact()" (§8.1) must hold on this path as well,
    # and it is the one most likely to grow free-text fields.
    rows = redact(
        [
            {"cite": f"[[{m.key}]]", "label": m.label, "value": m.display, "note": m.detail}
            for m in available
        ]
    )
    catalog = _render_catalog(rows)
    # The specialist findings are LLM-authored free text interpolated into this
    # prompt — scrub them as well before they travel to the model.
    safe_findings = redact({name: text for name, text in findings.items()})
    notes = "\n\n".join(
        f"[{name}] {text}" for name, text in safe_findings.items() if str(text).strip()
    )
    user = (
        "Combine the specialist notes below into a single overview of two or "
        "three short paragraphs, separated by a blank line. Reuse the [[token]] "
        "figures; never type a number. Stay descriptive — no advice, no "
        "forecasts. Prefer plain language.\n\n"
        f"All citable figures:\n{catalog}\n\n"
        f"Specialist notes:\n{notes or '(none)'}"
    )
    return await _ainvoke(llm, _SYSTEM, user)


# --------------------------------------------------------------------------- #
# Deterministic demo prose (no LLM) — used to regenerate the committed /demo
# artifact reproducibly. See docs/SPECS/A1.md §demo-artifact.
# --------------------------------------------------------------------------- #
def scripted_overview_prose(metrics: Mapping[str, Metric]) -> str:
    """A fixed, LLM-free narrative in the same token grammar the agents emit.

    This is what the committed demo artifact's narrative is generated from, so
    ``/demo`` never needs an API call and CI can regenerate it byte-for-byte. It
    cites only available metrics and reads like the agents' output.
    """

    def has(key: str) -> bool:
        m = metrics.get(key)
        return bool(m and m.available)

    paras: list[str] = []

    p1: list[str] = []
    if has("holdings_count"):
        p1.append("This portfolio spans [[holdings_count]] holdings")
        if has("equity_share"):
            p1.append(", with [[equity_share]] of current value in Indian and US equity")
        if has("us_exposure_share"):
            p1.append(" and [[us_exposure_share]] carrying US exposure")
        p1.append(".")
    if p1:
        paras.append("".join(p1))

    p2: list[str] = []
    if has("herfindahl_index"):
        p2.append("Concentration is measured by a Herfindahl index of [[herfindahl_index]] across holdings")
        if has("top_holding_weight"):
            p2.append(", the largest single position at [[top_holding_weight]] of value")
        if has("top3_weight"):
            p2.append(" and the top three at [[top3_weight]]")
        p2.append(".")
        if has("heaviest_sector_weight"):
            p2.append(" The heaviest sector is [[heaviest_sector_name]] at [[heaviest_sector_weight]] of the sector book.")
    if p2:
        paras.append("".join(p2))

    p3: list[str] = []
    if has("pnl"):
        p3.append("Overall return where a cost basis is known is [[pnl]]")
        if has("pnl_pct"):
            p3.append(" ([[pnl_pct]] on invested)")
        p3.append(".")
    if has("rows_without_cost_basis"):
        p3.append(" [[rows_without_cost_basis]] rows report no cost basis and are excluded from performance figures.")
    if has("wow_networth_delta"):
        p3.append(" Over the last week of captured history net worth moved [[wow_networth_delta]].")
    if has("sip_count"):
        p3.append(" [[sip_count]] systematic plans are on file")
        if has("sip_monthly_total"):
            p3.append(", contributing [[sip_monthly_total]] a month")
        p3.append(".")
    if p3:
        paras.append("".join(p3))

    return "\n\n".join(paras)


AsyncNode = Callable[[Any], Awaitable[Any]]


__all__ = [
    "OVERVIEW_MODEL",
    "OverviewLLMError",
    "SPECIALISTS",
    "default_llm_factory",
    "run_specialist",
    "run_synthesizer",
    "scripted_overview_prose",
]
