"""FD data integrity — stop presenting broken source data as ours (#65, slice).

The vendor's FD numbers cannot be corrected from here (verified against
`snapshot_raw`: 15,000 invested / 10,162 value / −4,838 P&L, frozen for days).
This file pins the four honest-data behaviours from the issue that need no
design decision; the history-chart rendering waits on #39:

1. The aggregate row is labelled "All fixed deposits", never `FD:FD_DEPOSITS`.
2. A `total_networth` vs `assets`-breakdown disagreement is logged with both
   figures (tolerance max(₹1, 0.1%)) — recorded, never silently served.
3. A bucket the prior snapshot held rows for, but which vanishes without a
   failure, marks the day partial (`BUCKET_VANISHED`). Nothing is backfilled.
4. A negative-P&L FD row carries a source caveat in its serialized note.

Uses the `networth_holdings__FD.json` fixture (the #65 shape, synthetic).
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

import services.snapshots as svc
from api.routes.portfolio import _holding_json
from db.models import SnapshotDay
from portfolio.connectors import StubConnector
from portfolio.connectors.ind_money import IndMoneyConnector
from portfolio.models import AssetType, Holding
from services.snapshots import BUCKET_VANISHED, BucketFailure
from tests.ind_money_transport import load

USER = "local"
NOW = datetime(2026, 8, 15, 6, 30, tzinfo=timezone.utc)


def _status(**payload):
    async def status() -> dict:
        return dict(payload)

    return status


def _connector(transport, **kwargs) -> IndMoneyConnector:
    from tests.test_portfolio_ind_money_connector import Sleeper

    return IndMoneyConnector(
        transport=transport,
        clock=lambda: NOW,
        sleep=Sleeper(),
        auth_status=_status(authenticated=True, expires_in_sec=3000),
        **kwargs,
    )


def _one_shot(payload):
    async def transport(tool: str, arguments=None):
        return payload

    return transport


def _fd_row(**overrides) -> dict:
    row = dict(load("networth_holdings__FD.json")["holdings"][0])
    row.update(overrides)
    return row


async def _holdings(payload: dict) -> list[Holding]:
    return await _connector(_one_shot(payload)).fetch_holdings(USER, AssetType.FD)


# --------------------------------------------------------------------------- #
# 1. The aggregate label
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_fd_aggregate_row_is_labelled_not_vendored() -> None:
    (holding,) = await _holdings(load("networth_holdings__FD.json"))
    assert holding.name == "All fixed deposits"
    # Identity is untouched: only the display label changed.
    assert holding.external_id == "FD:FD_DEPOSITS"


@pytest.mark.asyncio
async def test_named_fd_row_keeps_its_name() -> None:
    (holding,) = await _holdings({"holdings": [_fd_row(investment="Fixture Tax Saver Deposit")]})
    assert holding.name == "Fixture Tax Saver Deposit"


@pytest.mark.asyncio
async def test_nameless_partial_fd_row_keeps_no_name() -> None:
    """An empty name that is NOT the whole bucket must not wear the aggregate's
    label — it is an unnamed position, not every deposit."""
    (holding,) = await _holdings({"holdings": [_fd_row(holding_percent=50)]})
    assert holding.name is None


# --------------------------------------------------------------------------- #
# 2. Total-vs-breakdown reconciliation
# --------------------------------------------------------------------------- #


def _snapshot_payload() -> dict:
    return copy.deepcopy(load("networth_snapshot.json"))


@pytest.mark.asyncio
async def test_breakdown_disagreement_is_logged_not_silenced(caplog) -> None:
    """The 2026-08-20 shape: FD inside `total_networth`, outside `assets`."""
    payload = _snapshot_payload()
    short = payload["assets"][:-1]
    assert short != payload["assets"]  # the test actually drops a bucket
    payload["assets"] = short
    with caplog.at_level(logging.WARNING, logger="portfolio.connectors.ind_money"):
        snapshot = await _connector(_one_shot(payload)).fetch_snapshot(USER)
    assert any("differs from its assets-breakdown sum" in m for m in caplog.messages)
    # Both figures are still served as-is: nothing is recomputed or "fixed".
    assert snapshot.net_worth == Decimal(str(payload["total_networth"]))


@pytest.mark.asyncio
async def test_reconciling_snapshot_stays_quiet(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="portfolio.connectors.ind_money"):
        await _connector(_one_shot(_snapshot_payload())).fetch_snapshot(USER)
    assert not [m for m in caplog.messages if "assets-breakdown sum" in m]


# --------------------------------------------------------------------------- #
# 4. The negative-P&L caveat
# --------------------------------------------------------------------------- #


def _holding(**overrides: Any) -> Holding:
    base: dict[str, Any] = {
        "source": "ind_money",
        "external_id": "FD:FD_DEPOSITS",
        "asset_type": AssetType.FD,
        "current_value": Decimal("10162"),
        "invested_amount": Decimal("15000"),
        "currency": "INR",
        "as_of": NOW,
    }
    base.update(overrides)
    return Holding(**base)


def test_negative_fd_pnl_carries_a_caveat() -> None:
    body = _holding_json(_holding(pnl=Decimal("-4838"), pnl_pct=Decimal("-32.25")))
    assert body["note"] and "stale source record" in body["note"]
    assert "FD:FD_DEPOSITS" not in body["note"]


def test_healthy_rows_carry_no_note() -> None:
    assert _holding_json(_holding(pnl=Decimal("120")) )["note"] is None
    assert _holding_json(_holding(pnl=None))["note"] is None
    mf = _holding(asset_type=AssetType.MF, external_id="MF:FIXT1", pnl=Decimal("-5"))
    assert _holding_json(mf)["note"] is None


# --------------------------------------------------------------------------- #
# 3. Vanish detection
# --------------------------------------------------------------------------- #


class _NoFdStub(StubConnector):
    """The demo portfolio with FD erased from the snapshot, as if the vendor
    omitted the bucket: no slice to value, nothing to enumerate."""

    async def fetch_snapshot(self, user_id: str):
        snapshot = await super().fetch_snapshot(user_id)
        return snapshot.model_copy(
            update={
                "by_asset_type": [
                    s for s in snapshot.by_asset_type
                    if s.asset_type is not AssetType.FD
                ]
            }
        )


async def _no_sleep(seconds: float) -> None:
    return None


async def _fx_ok():
    return None


async def _capture(session, connector, now: datetime):
    return await svc.capture_user(
        session, USER, connector=connector, now=now,
        fx=_fx_ok, sleep=_no_sleep, call_spacing=0,
    )


@pytest.mark.asyncio
async def test_vanished_bucket_marks_the_day_partial(db_session) -> None:
    day_one = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    day_two = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    first = await _capture(db_session, StubConnector(), day_one)
    assert first.status == svc.CAPTURED
    assert not [f for f in first.buckets_failed if f.reason == BUCKET_VANISHED]

    second = await _capture(db_session, _NoFdStub(), day_two)
    assert second.status == svc.CAPTURED
    vanished = [f for f in second.buckets_failed if f.reason == BUCKET_VANISHED]
    assert [f.asset_type for f in vanished] == ["FD"]

    stored = (
        await db_session.execute(
            select(SnapshotDay).where(
                SnapshotDay.user_id == USER,
                SnapshotDay.captured_on == svc.attributed_day(day_two),
            )
        )
    ).scalar_one()
    assert stored.buckets_failed is not None
    assert {"asset_type": "FD", "reason": BUCKET_VANISHED} in stored.buckets_failed


@pytest.mark.asyncio
async def test_first_capture_has_nothing_to_vanish(db_session) -> None:
    outcome = await _capture(
        db_session, _NoFdStub(), datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    )
    assert outcome.status == svc.CAPTURED
    assert not [f for f in outcome.buckets_failed if f.reason == BUCKET_VANISHED]


def test_bucket_failure_carries_the_new_reason() -> None:
    assert BucketFailure("FD", BUCKET_VANISHED).as_dict() == {
        "asset_type": "FD",
        "reason": "vanished",
    }
