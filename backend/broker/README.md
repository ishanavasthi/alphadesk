# Broker Integration

Order placement is **not** in the current scope of AlphaDesk. This package
defines the interface for a future broker integration.

The `BrokerAdapter` abstract base class in `base.py` defines the contract a
concrete broker implementation must satisfy.

## Adding a broker (e.g. Dhan)

1. Create `backend/broker/dhan.py` implementing `BrokerAdapter`.
2. Set `BROKER=dhan` in `.env`.
3. The Execution agent already calls `broker.place_order()` — no agent code
   changes needed.
4. Add HiTL confirmation for order value > ₹10,000 (already stubbed in
   `execution.py`).
