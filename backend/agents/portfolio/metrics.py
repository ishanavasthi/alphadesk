"""Deterministic portfolio metrics — the only place a number is ever produced.

**Every figure the AI overview may cite is computed here, in Python, from the
verified M1 model.** The agents downstream narrate these values by key and are
structurally unable to introduce a number of their own (see ``narrative.py``).
That is the card's ironclad rule stated as code: an LLM never does arithmetic on
someone's holdings.

Three portfolios must all produce sane metrics — never a crash, never a
fabricated number:

- **one holding** → concentration is maximal (HHI ``1.00``, top weight
  ``100.0%``); that is a real warning, not an error;
- **no ``invested_amount`` anywhere** → every performance metric is
  ``available=False`` (P&L, return, cost-basis rows), so the overview makes no
  performance claim rather than a fabricated one;
- **empty** → aggregates are ``None``/unavailable and the concentration metrics
  degrade to unavailable instead of dividing by zero.

Weights and concentration are computed over the **holding rows we actually have**
(denominator = the sum of their values), never over the snapshot's headline
total — the two do not reconcile by construction (M1 §5), and dividing a row by a
total it is not part of would misstate every weight. Allocation-share metrics
(equity share, US exposure, heaviest sector) come off the snapshot's own
breakdown slices, which is where those buckets are enumerated.

**No XIRR, ever** (C2 killed it): the return metric is the simple ``pnl_pct``
already derived by the model, and it is only shown when a cost basis exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Optional, Sequence

from portfolio.models import (
    AllocationSlice,
    AssetType,
    Holding,
    PortfolioSnapshot,
    Sip,
    is_us_exposure,
    sum_holdings_value,
)

#: SIP statuses that count as currently contributing. Anything else (paused,
#: cancelled, unknown) is held but not adding money, so it is excluded from the
#: monthly-total figure while still counted in the roster.
_ACTIVE_SIP_STATUSES = frozenset({"active", "running", "live"})

#: Asset-type strings that count as equity exposure for the "equity share"
#: metric. ``US_STOCK_WALLET`` is the vendor's out-of-enum US cash-equity bucket
#: (it lands as ``UNKNOWN`` with the raw string preserved).
EQUITY_TYPES = frozenset({"IND_STOCK", "US_STOCK", "US_STOCK_WALLET"})

#: Herfindahl bands, low → high. A one-holding book sits at 1.0 ("concentrated").
_HHI_MODERATE = Decimal("0.15")
_HHI_HIGH = Decimal("0.25")

#: How close two history points must be to a 7-day gap to count as "a week ago".
_WOW_MIN_DAYS = 4
_WOW_MAX_DAYS = 11


# --------------------------------------------------------------------------- #
# The metric value type
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Metric:
    """One computed figure, with a stable ``key`` and a canonical ``display``.

    ``display`` is the exact string the narrative renders in its metric chip, so
    it is also the string the "no invented figures" test checks the narrative
    against. ``value`` / ``text`` carry the raw values for anything that wants to
    do its own formatting.
    """

    key: str
    label: str
    unit: str  # "inr" | "pct" | "ratio" | "count" | "text"
    available: bool
    display: str
    value: Optional[Decimal] = None
    text: Optional[str] = None
    detail: Optional[str] = None
    signed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "unit": self.unit,
            "available": self.available,
            "display": self.display,
            "value": None if self.value is None else format(self.value, "f"),
            "text": self.text,
            "detail": self.detail,
            "signed": self.signed,
        }


# --------------------------------------------------------------------------- #
# Formatting — canonical, en-IN grouping, no locale dependency
# --------------------------------------------------------------------------- #
def _group_indian(digits: str) -> str:
    """`1007655` -> `10,07,655` (the Indian 2-2-3 grouping), string in/out."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def format_inr(value: Optional[Decimal], *, signed: bool = False) -> str:
    if value is None:
        return "—"
    rounded = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    body = _group_indian(str(abs(rounded)))
    if signed:
        sign = "+" if rounded >= 0 else "−"  # a real minus sign
        return f"{sign}₹{body}"
    return f"₹{body}"


def format_pct(value: Optional[Decimal], *, digits: int = 1, signed: bool = False) -> str:
    if value is None:
        return "—"
    q = Decimal(1).scaleb(-digits)
    rounded = value.quantize(q, rounding=ROUND_HALF_UP)
    if signed:
        sign = "+" if rounded >= 0 else "−"
        return f"{sign}{abs(rounded)}%"
    return f"{rounded}%"


def format_ratio(value: Optional[Decimal], *, digits: int = 2) -> str:
    if value is None:
        return "—"
    q = Decimal(1).scaleb(-digits)
    return str(value.quantize(q, rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# Small numeric helpers
# --------------------------------------------------------------------------- #
def _pct_of(part: Optional[Decimal], whole: Optional[Decimal]) -> Optional[Decimal]:
    if part is None or whole is None or whole == 0:
        return None
    return part / whole * Decimal(100)


def _slice_type_key(s: AllocationSlice) -> Optional[str]:
    """The raw asset-type string a by_asset_type slice represents, if any."""
    if s.asset_type_raw:
        return s.asset_type_raw.strip().upper()
    if s.asset_type is not None and s.asset_type is not AssetType.UNKNOWN:
        return s.asset_type.value
    return None


def _hhi_band(hhi: Decimal) -> str:
    if hhi >= _HHI_HIGH:
        return "concentrated"
    if hhi >= _HHI_MODERATE:
        return "moderate"
    return "diversified"


# --------------------------------------------------------------------------- #
# History point (a S1 snapshot day, decoupled from the DB)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HistoryPoint:
    day: date
    net_worth: Decimal


def to_history_points(rows: Iterable[Any]) -> list[HistoryPoint]:
    """Normalize S1 ``history_points`` rows into local ``HistoryPoint``s.

    Accepts anything with ``captured_on``/``day`` and ``total_value``/
    ``net_worth`` attributes, oldest-or-newest order — it is sorted here.
    """
    out: list[HistoryPoint] = []
    for row in rows or []:
        day = getattr(row, "captured_on", None) or getattr(row, "day", None)
        value = getattr(row, "total_value", None)
        if value is None:
            value = getattr(row, "net_worth", None)
        if day is None or value is None:
            continue
        out.append(HistoryPoint(day=day, net_worth=Decimal(str(value))))
    out.sort(key=lambda p: p.day)
    return out


# --------------------------------------------------------------------------- #
# The metric computations
# --------------------------------------------------------------------------- #
def compute_metrics(
    snapshot: PortfolioSnapshot,
    holdings: Sequence[Holding],
    *,
    history: Optional[Sequence[HistoryPoint]] = None,
    sips: Optional[Sequence[Sip]] = None,
) -> list[Metric]:
    """Compute the full ordered metric list from verified inputs.

    None of the inputs is trusted to be non-empty; each metric decides for
    itself whether it can be computed and, if not, is emitted with
    ``available=False`` and a ``—`` display rather than omitted — the rail always
    lists every metric so a gap is visible, not silent.
    """
    metrics: list[Metric] = []
    gross = snapshot.gross_value
    invested = snapshot.invested_total

    # -- Headline aggregates -------------------------------------------------
    metrics.append(
        Metric(
            key="net_worth",
            label="Net worth",
            unit="inr",
            available=True,
            display=format_inr(snapshot.net_worth),
            value=snapshot.net_worth,
            detail="net of liabilities",
        )
    )
    metrics.append(
        Metric(
            key="current_value",
            label="Current value",
            unit="inr",
            available=gross is not None,
            display=format_inr(gross),
            value=gross,
        )
    )
    metrics.append(
        Metric(
            key="invested_total",
            label="Invested",
            unit="inr",
            available=invested is not None,
            display=format_inr(invested),
            value=invested,
            detail="where cost basis is known" if invested is not None else "not reported",
        )
    )

    # -- Return (simple pnl_pct — never XIRR, only when a cost basis exists) --
    pnl: Optional[Decimal] = None
    pnl_pct: Optional[Decimal] = None
    if gross is not None and invested is not None and invested != 0:
        pnl = gross - invested
        pnl_pct = pnl / invested * Decimal(100)
    metrics.append(
        Metric(
            key="pnl",
            label="Overall return",
            unit="inr",
            available=pnl is not None,
            display=format_inr(pnl, signed=True),
            value=pnl,
            signed=True,
            detail="no cost basis reported" if pnl is None else None,
        )
    )
    metrics.append(
        Metric(
            key="pnl_pct",
            label="Return on invested",
            unit="pct",
            available=pnl_pct is not None,
            display=format_pct(pnl_pct, signed=True),
            value=pnl_pct,
            signed=True,
        )
    )

    # -- Counts --------------------------------------------------------------
    total_rows = len(holdings)
    no_basis = sum(1 for h in holdings if h.invested_amount is None)
    metrics.append(
        Metric(
            key="holdings_count",
            label="Holdings",
            unit="count",
            available=True,
            display=str(total_rows),
            value=Decimal(total_rows),
        )
    )
    metrics.append(
        Metric(
            key="rows_without_cost_basis",
            label="Rows without cost basis",
            unit="count",
            available=True,
            display=str(no_basis),
            value=Decimal(no_basis),
            detail=f"of {total_rows}" if total_rows else None,
        )
    )

    # -- Concentration over holding rows ------------------------------------
    metrics.extend(_concentration_metrics(holdings))

    # -- Allocation shares off the snapshot's breakdown slices --------------
    metrics.append(_equity_share_metric(snapshot.by_asset_type, gross))
    metrics.append(_us_exposure_metric(snapshot.by_asset_type, gross))
    metrics.extend(_sector_metrics(snapshot.by_sector))

    # -- Systematic investments (SIP roster) --------------------------------
    metrics.extend(_sip_metrics(sips))

    # -- Week-over-week net worth from S1 snapshots -------------------------
    metrics.extend(_wow_metrics(history))

    return metrics


def _sip_metrics(sips: Optional[Sequence[Sip]]) -> list[Metric]:
    rows = list(sips or [])
    active = [s for s in rows if (s.status or "").strip().lower() in _ACTIVE_SIP_STATUSES]
    monthly: Optional[Decimal] = None
    if active:
        amounts = [s.amount for s in active if s.amount is not None]
        monthly = sum(amounts, Decimal(0)) if amounts else None
    return [
        Metric(
            key="sip_count",
            label="SIPs on file",
            unit="count",
            available=True,
            display=str(len(rows)),
            value=Decimal(len(rows)),
            detail=f"{len(active)} active" if rows else None,
        ),
        Metric(
            key="sip_monthly_total",
            label="Active monthly SIP",
            unit="inr",
            available=monthly is not None,
            display=format_inr(monthly),
            value=monthly,
            detail="across active SIPs" if monthly is not None else None,
        ),
    ]


def _concentration_metrics(holdings: Sequence[Holding]) -> list[Metric]:
    total = sum_holdings_value(holdings)
    valued = [h for h in holdings if h.current_value is not None]
    can = total is not None and total > 0 and bool(valued)

    hhi: Optional[Decimal] = None
    top_weight: Optional[Decimal] = None
    top_name: Optional[str] = None
    top3_weight: Optional[Decimal] = None

    if can:
        weights = sorted(
            ((h.current_value / total, h) for h in valued),
            key=lambda pair: pair[0],
            reverse=True,
        )
        hhi = sum((w * w for w, _ in weights), Decimal(0))
        top_w, top_h = weights[0]
        top_weight = top_w * Decimal(100)
        top_name = top_h.name or top_h.symbol or top_h.external_id
        top3_weight = sum((w for w, _ in weights[:3]), Decimal(0)) * Decimal(100)

    band = _hhi_band(hhi) if hhi is not None else None
    return [
        Metric(
            key="herfindahl_index",
            label="Herfindahl index (holdings)",
            unit="ratio",
            available=hhi is not None,
            display=format_ratio(hhi),
            value=hhi,
            detail=band,
        ),
        Metric(
            key="top_holding_weight",
            label="Top holding weight",
            unit="pct",
            available=top_weight is not None,
            display=format_pct(top_weight),
            value=top_weight,
            detail=top_name,
        ),
        Metric(
            key="top_holding_name",
            label="Largest position",
            unit="text",
            available=top_name is not None,
            display=top_name or "—",
            text=top_name,
        ),
        Metric(
            key="top3_weight",
            label="Top-3 weight",
            unit="pct",
            available=top3_weight is not None,
            display=format_pct(top3_weight),
            value=top3_weight,
        ),
    ]


def _equity_share_metric(
    by_asset_type: Sequence[AllocationSlice], gross: Optional[Decimal]
) -> Metric:
    equity = Decimal(0)
    seen = False
    for s in by_asset_type:
        key = _slice_type_key(s)
        if key in EQUITY_TYPES and s.current_value is not None:
            equity += s.current_value
            seen = True
    denom = gross if gross is not None else _slice_total(by_asset_type)
    share = _pct_of(equity, denom) if seen else None
    return Metric(
        key="equity_share",
        label="Equity share",
        unit="pct",
        available=share is not None,
        display=format_pct(share),
        value=share,
        detail="Indian + US equity" if share is not None else None,
    )


def _us_exposure_metric(
    by_asset_type: Sequence[AllocationSlice], gross: Optional[Decimal]
) -> Metric:
    us = Decimal(0)
    seen = False
    for s in by_asset_type:
        at = s.asset_type
        if at is not None and is_us_exposure(at, s.asset_type_raw) and s.current_value is not None:
            us += s.current_value
            seen = True
    denom = gross if gross is not None else _slice_total(by_asset_type)
    share = _pct_of(us, denom) if seen else None
    return Metric(
        key="us_exposure_share",
        label="US exposure",
        unit="pct",
        available=share is not None,
        display=format_pct(share),
        value=share,
        detail="foreign-denominated, source-converted to INR" if share is not None else None,
    )


def _slice_total(slices: Sequence[AllocationSlice]) -> Optional[Decimal]:
    total = sum((s.current_value for s in slices if s.current_value is not None), Decimal(0))
    return total if total > 0 else None


def _sector_metrics(by_sector: Sequence[AllocationSlice]) -> list[Metric]:
    total = _slice_total(by_sector)
    valued = [s for s in by_sector if s.current_value is not None]
    heaviest_pct: Optional[Decimal] = None
    heaviest_label: Optional[str] = None
    sector_hhi: Optional[Decimal] = None
    if total is not None and valued:
        weights = [(s.current_value / total, s) for s in valued]
        sector_hhi = sum((w * w for w, _ in weights), Decimal(0))
        top_w, top_s = max(weights, key=lambda pair: pair[0])
        heaviest_pct = top_w * Decimal(100)
        heaviest_label = top_s.label or None

    return [
        Metric(
            key="heaviest_sector_weight",
            label="Heaviest sector",
            unit="pct",
            available=heaviest_pct is not None,
            display=format_pct(heaviest_pct),
            value=heaviest_pct,
            detail=heaviest_label,
        ),
        Metric(
            key="heaviest_sector_name",
            label="Heaviest sector name",
            unit="text",
            available=heaviest_label is not None,
            display=heaviest_label or "—",
            text=heaviest_label,
        ),
        Metric(
            key="sector_hhi",
            label="Sector concentration (HHI)",
            unit="ratio",
            available=sector_hhi is not None,
            display=format_ratio(sector_hhi),
            value=sector_hhi,
            detail=_hhi_band(sector_hhi) if sector_hhi is not None else None,
        ),
        Metric(
            key="sector_count",
            label="Sectors held",
            unit="count",
            available=True,
            display=str(len(valued)),
            value=Decimal(len(valued)),
        ),
    ]


def _wow_metrics(history: Optional[Sequence[HistoryPoint]]) -> list[Metric]:
    points = list(history or [])
    delta: Optional[Decimal] = None
    delta_pct: Optional[Decimal] = None
    if len(points) >= 2:
        points = sorted(points, key=lambda p: p.day)
        latest = points[-1]
        # The point closest to a 7-day gap, within [4, 11] days.
        prior: Optional[HistoryPoint] = None
        best_gap: Optional[int] = None
        for p in points[:-1]:
            gap = (latest.day - p.day).days
            if _WOW_MIN_DAYS <= gap <= _WOW_MAX_DAYS:
                score = abs(gap - 7)
                if best_gap is None or score < best_gap:
                    best_gap = score
                    prior = p
        if prior is not None:
            delta = latest.net_worth - prior.net_worth
            if prior.net_worth != 0:
                delta_pct = delta / prior.net_worth * Decimal(100)
    return [
        Metric(
            key="wow_networth_delta",
            label="1-week Δ net worth",
            unit="inr",
            available=delta is not None,
            display=format_inr(delta, signed=True),
            value=delta,
            signed=True,
            detail="over the last week of captured history" if delta is not None else "needs a week of snapshots",
        ),
        Metric(
            key="wow_networth_delta_pct",
            label="1-week Δ net worth %",
            unit="pct",
            available=delta_pct is not None,
            display=format_pct(delta_pct, signed=True),
            value=delta_pct,
            signed=True,
        ),
    ]


def metrics_by_key(metrics: Sequence[Metric]) -> dict[str, Metric]:
    return {m.key: m for m in metrics}


def metrics_json(metrics: Sequence[Metric]) -> list[dict[str, Any]]:
    return [m.as_dict() for m in metrics]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "EQUITY_TYPES",
    "HistoryPoint",
    "Metric",
    "compute_metrics",
    "format_inr",
    "format_pct",
    "format_ratio",
    "metrics_by_key",
    "metrics_json",
    "to_history_points",
]
