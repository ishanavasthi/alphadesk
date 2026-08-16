"""Narrative types, prose→segment parsing, and the anti-fabrication check.

The narrative is not free text with numbers in it. It is a list of paragraphs,
each a list of **segments**, where a segment is either literal prose or a
reference to a computed metric by key:

    {"segments": [
        {"text": "Your largest position is "},
        {"metric": "top_holding_weight", "display": "21.7%", "label": "..."},
        {"text": " of value."},
    ]}

The LLM writes prose and marks every figure it wants to cite with a
``[[metric_key]]`` token; it is instructed never to type a numeral itself.
``parse_prose`` turns that into segments, substituting the metric's **Python-
computed** ``display`` for each token. The number therefore never originates in
the model — only the choice of which metric to cite does. ``verify`` closes the
loop: it renders the narrative to plain text and asserts every figure in it
appears in the returned metric set, so a model that slipped a numeral into its
prose is caught rather than trusted.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from agents.portfolio.metrics import Metric

_TOKEN_RE = re.compile(r"\[\[\s*([a-zA-Z0-9_]+)\s*\]\]")

#: Any run of characters that includes a digit, plus the money/percent/sign
#: glyphs that attach to it. Used to find "figures" in rendered narrative text.
_FIGURE_RE = re.compile(r"[₹%+\-−]?\d[\d,]*\.?\d*%?")


def _metric_segment(metric: Metric) -> dict[str, Any]:
    return {
        "metric": metric.key,
        "display": metric.display,
        "label": metric.label,
        "detail": metric.detail,
        "available": metric.available,
    }


def parse_prose(text: str, metrics: Mapping[str, Metric]) -> list[dict[str, Any]]:
    """Turn ``[[key]]``-marked prose into a list of paragraph dicts.

    Paragraphs are split on blank lines. A token naming a known metric becomes a
    metric segment carrying that metric's computed display; a token naming an
    unknown metric is dropped (its surrounding prose is kept), so a hallucinated
    key can never smuggle a value in.
    """
    paragraphs: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", (text or "").strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        segments: list[dict[str, Any]] = []
        pos = 0
        for match in _TOKEN_RE.finditer(block):
            if match.start() > pos:
                lead = block[pos : match.start()]
                if lead:
                    segments.append({"text": lead})
            key = match.group(1)
            metric = metrics.get(key)
            if metric is not None:
                segments.append(_metric_segment(metric))
            pos = match.end()
        if pos < len(block):
            tail = block[pos:]
            if tail:
                segments.append({"text": tail})
        segments = _tidy(segments)
        if segments:
            paragraphs.append({"segments": segments})
    return paragraphs


def _tidy(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse whitespace runs left by dropped tokens; drop empty text."""
    out: list[dict[str, Any]] = []
    for seg in segments:
        if "text" in seg:
            cleaned = re.sub(r"[ \t]+", " ", seg["text"])
            if cleaned == "":
                continue
            out.append({"text": cleaned})
        else:
            out.append(seg)
    return out


def render_plain(narrative: Sequence[Mapping[str, Any]]) -> str:
    """Flatten a narrative to plain text — prose plus each chip's display."""
    parts: list[str] = []
    for para in narrative:
        chunk: list[str] = []
        for seg in para.get("segments", []):
            if "text" in seg:
                chunk.append(str(seg["text"]))
            elif "display" in seg:
                chunk.append(str(seg["display"]))
        parts.append("".join(chunk))
    return "\n\n".join(parts)


def figures(text: str) -> list[str]:
    """Every figure-like token in ``text`` (anything containing a digit)."""
    return [m.group(0).strip() for m in _FIGURE_RE.finditer(text) if m.group(0).strip()]


def invented_figures(
    narrative: Sequence[Mapping[str, Any]], metrics: Sequence[Metric] | None = None
) -> list[str]:
    """Figures the model wrote as free prose rather than as a metric chip.

    Empty list ⇒ every number in the narrative reached the reader **only as a
    metric chip** (a ``[[token]]`` the synthesizer emitted, rendered from the
    Python-computed ``display``). A number typed into a ``{"text"}`` segment is,
    by definition, one the model wrote itself — so **any digit in a text segment
    is flagged**, and the caller trips the scripted-prose fallback.

    This is structural, not a substring trace: a substring check let a fabricated
    but plausible numeral pass whenever it happened to be a substring of some
    real display (``1.7%`` inside a ``21.7%`` chip, ``5 names``, a rupee
    fragment). Numbers are allowed in the narrative **only** through chips, and a
    chip's figure is always a computed display — so the ``metrics`` argument is no
    longer needed to decide provenance and is accepted only for compatibility.
    """
    offenders: list[str] = []
    for para in narrative:
        for seg in para.get("segments", []):
            if "text" in seg:
                offenders.extend(figures(str(seg["text"])))
    return offenders


__all__ = [
    "figures",
    "invented_figures",
    "parse_prose",
    "render_plain",
]
