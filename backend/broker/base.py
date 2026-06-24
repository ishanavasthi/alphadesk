"""BrokerAdapter abstract base class + loader (stub).

Defines the contract a concrete broker (e.g. ``backend/broker/dhan.py``) must
implement for live order placement, plus :func:`load_broker` which returns the
configured adapter or ``None``. No concrete adapters ship yet, so live trading is
disabled by default and the Execution agent operates a paper watchlist only.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field

from graph.state import PendingAction


class OrderResult(BaseModel):
    """Typed result of a broker order placement."""

    order_id: Optional[str] = Field(None, description="Broker-assigned order id, if accepted.")
    status: str = Field(..., description="Order status, e.g. 'placed', 'rejected'.")
    message: Optional[str] = Field(None, description="Human-readable detail from the broker.")


class BrokerAdapter(ABC):
    """Interface every concrete broker integration must implement."""

    name: str = "base"

    @abstractmethod
    def place_order(self, action: PendingAction) -> OrderResult:
        """Place (or simulate) an order for the given approved action."""
        raise NotImplementedError


def load_broker() -> Optional[BrokerAdapter]:
    """Return the configured ``BrokerAdapter``, or ``None`` when live trading is disabled.

    Reads the ``BROKER`` env var. Concrete adapters register here once implemented
    (see ``backend/broker/README.md``). None are shipped yet, so this returns
    ``None`` and the Execution agent keeps actions in the paper watchlist.
    """
    name = os.environ.get("BROKER", "").strip().lower()
    if not name:
        return None
    # e.g. if name == "dhan": from broker.dhan import DhanAdapter; return DhanAdapter()
    return None
