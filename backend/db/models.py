"""AlphaDesk identity, broker-link and daily-snapshot tables (cards F1 + S1).

    users              the person. `id` is the Clerk `user_id` (a string, not a
                       UUID) so F2 can adopt Clerk without a key migration.
    broker_links       one row per (user, broker source). Holds the OAuth
                       material needed to keep a link alive: encrypted
                       access/refresh tokens, the dynamically-registered client
                       credentials, and the token endpoint to refresh against.
    oauth_pending      short-lived rows for an in-flight authorization-code
                       flow, keyed by the OAuth `state`. TTL 10 minutes, single
                       use — both enforced in application code (F3), not by the
                       DB.
    snapshot_days      one row per (user, attributed IST calendar day): the
                       source's own net-worth total, plus the day's USD/INR
                       reference rate. Card S1.
    snapshot_holdings  the normalized `Holding` rows behind one snapshot day.
    snapshot_raw       the source payloads those rows were mapped from, kept
                       for forensics and pruned at 90 days.

**Cascade semantics.** `broker_links.user_id`, `oauth_pending.user_id`,
`snapshot_days.user_id` and `watchlist.user_id` are declared `ON DELETE CASCADE`
*at the FK level*, as are `snapshot_holdings.snapshot_id` and
`snapshot_raw.snapshot_id`. Deleting a `users` row therefore wipes every
dependent row — including the user's entire net-worth history and paper
watchlist — inside Postgres. A later "delete my data" card relies on
that being a schema guarantee rather than an ORM-relationship convention: a raw
`DELETE FROM users` from psql or a migration is just as safe as an ORM
`session.delete(user)`.

Every `*_enc` column is an opaque Fernet token — see `db.crypto`. Never select
one into a log line.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware `now`. All timestamps in this schema are `timestamptz`."""
    return datetime.now(timezone.utc)


def _ts_column(*, nullable: bool = False) -> Column:
    return Column(DateTime(timezone=True), nullable=nullable)


class User(SQLModel, table=True):
    """A person using AlphaDesk. `id` is the Clerk user_id once F2 lands."""

    __tablename__ = "users"

    id: str = Field(primary_key=True, max_length=255)
    email: str | None = Field(default=None, max_length=320, index=True)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class BrokerLink(SQLModel, table=True):
    """A live (or lapsed) OAuth link between a user and a data source.

    `source` is the connector key — `"ind_money"` today. One link per
    (user, source): re-linking updates the row rather than adding a second.
    """

    __tablename__ = "broker_links"
    __table_args__ = (
        UniqueConstraint("user_id", "source", name="uq_broker_links_user_source"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
        max_length=255,
    )
    source: str = Field(max_length=64)

    # --- credentials (encrypted; see db.crypto) --------------------------
    access_token_enc: str | None = Field(default=None)
    refresh_token_enc: str | None = Field(default=None)
    expires_at: datetime | None = Field(
        default=None, sa_column=_ts_column(nullable=True)
    )

    # --- the client this link was issued to (dynamic client registration) -
    client_id: str | None = Field(default=None, max_length=255)
    client_secret_enc: str | None = Field(default=None)
    token_url: str | None = Field(default=None, max_length=2048)
    scope: str | None = Field(default=None, max_length=1024)
    #: The redirect URI this client was registered against (F3). Dynamic client
    #: registration binds a client to its `redirect_uris`, so a stored client is
    #: only reusable while the callback URL is unchanged — a deploy that moves
    #: the backend origin has to register a new one, and without this column
    #: there is no way to know that except by failing the login.
    redirect_uri: str | None = Field(default=None, max_length=2048)

    # --- link health ------------------------------------------------------
    supports_refresh: bool = Field(default=False)
    status: str = Field(default="active", max_length=32)
    linked_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())
    last_refresh_at: datetime | None = Field(
        default=None, sa_column=_ts_column(nullable=True)
    )


class OAuthPending(SQLModel, table=True):
    """One in-flight authorization-code + PKCE flow, keyed by the OAuth `state`.

    Rows are consumed by the callback and are only valid for 10 minutes. Both
    the TTL and the single-use rule are enforced in application code (F3) —
    the DB stores `created_at` and nothing more.
    """

    __tablename__ = "oauth_pending"

    state: str = Field(primary_key=True, max_length=255)
    user_id: str = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
        max_length=255,
    )
    source: str = Field(max_length=64)
    verifier: str = Field(max_length=255)
    redirect_uri: str = Field(max_length=2048)
    client_id: str | None = Field(default=None, max_length=255)
    client_secret_enc: str | None = Field(default=None)
    token_url: str | None = Field(default=None, max_length=2048)
    created_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


# --------------------------------------------------------------------------- #
# Paper watchlist (card F4)
# --------------------------------------------------------------------------- #
class Watchlist(SQLModel, table=True):
    """One stock a user approved into their paper watchlist (card F4).

    The Lab itself is an ephemeral, labelled simulation — its runs live only in
    memory and are lost on restart. The paper watchlist is the **one** thing
    that outlives a run, so it is the one thing that persists here.

    **Denormalized on purpose.** Each row is a self-contained decision record —
    the thesis, confidence, action and risk verdict as they stood at approval —
    rather than a foreign key into the run that produced it. A Lab run is gone
    after a restart, so a normalized "join back to the run" would leave every
    watchlist row unreadable the first time the process bounces. `run_id` is
    kept as an **opaque, non-FK** reference: "view the original run" resolves it
    if the run is still in memory and degrades to "this run is no longer
    available" when it is not — never a broken join, never a silent recompute.

    `PK (user_id, symbol)` — a stock a user already holds is not added twice;
    the first decision to reach the watchlist is the one that stays.
    """

    __tablename__ = "watchlist"

    user_id: str = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        primary_key=True,
        max_length=255,
    )
    symbol: str = Field(primary_key=True, max_length=64)
    company: str | None = Field(default=None, max_length=255)
    thesis: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    confidence: float | None = Field(default=None)
    action: str | None = Field(default=None, max_length=32)
    risk_verdict: str | None = Field(default=None, max_length=32)
    query: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    #: The Lab run this decision came from. **Opaque and non-FK** — the runs
    #: table does not exist (Lab runs are in-memory), so this may reference a run
    #: that no longer resolves. Never joined, never a foreign key.
    run_id: str | None = Field(default=None, max_length=255)
    added_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


# --------------------------------------------------------------------------- #
# Daily snapshots (card S1)
# --------------------------------------------------------------------------- #
#: Money columns. 18 digits with 2 decimals holds any plausible net worth
#: without the binary-float rounding a `double precision` column would
#: reintroduce after M1 went to the trouble of keeping everything `Decimal`.
def _money_column(*, nullable: bool = False) -> Column:
    return Column(Numeric(18, 2), nullable=nullable)


class SnapshotDay(SQLModel, table=True):
    """One user's portfolio, as it stood on one attributed IST calendar day.

    `captured_on` is **not** a date the source supplied — no IND Money payload
    carries one (C2). It is derived from the capture time through the single IST
    helper in `services.snapshots`, with any run before 06:00 IST attributed to
    the previous IST calendar day. That cutoff is what makes the ~01:00 IST
    retry land on the same day as the 23:45 IST primary run.

    `UNIQUE (user_id, captured_on)` is the idempotency guarantee: a second
    capture on the same attributed day is a no-op, not a second row.

    `total_value` is the source's own headline total, passed straight through.
    It is deliberately **not** the sum of `snapshot_holdings` and must never be
    asserted equal to it — the un-enumerable US-stock wallet bucket alone makes
    the two differ by ~2.3% (M1 §5).
    """

    __tablename__ = "snapshot_days"
    __table_args__ = (
        UniqueConstraint("user_id", "captured_on", name="uq_snapshot_days_user_day"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
        max_length=255,
    )
    #: The IST calendar day this capture is attributed to. Never a UTC or
    #: server-local "today".
    captured_on: date = Field(sa_column=Column(Date, nullable=False))
    total_value: Decimal = Field(sa_column=_money_column())
    currency: str = Field(default="INR", max_length=8)
    #: The day's USD/INR reference rate, or NULL when the FX fetch failed. A
    #: failed rate must never fail a snapshot: the rate is display math, the
    #: snapshot is unrecoverable data.
    usd_inr_rate: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    #: Buckets the snapshot reported but whose rows could not be read, as
    #: ``[{"asset_type": "MF", "reason": "throttled"}, …]``. **NULL means the
    #: capture was complete** — a clean day leaves no marker at all.
    #:
    #: This lives on the day, not in `snapshot_raw`, precisely because
    #: `snapshot_raw` is pruned at 90 days while the day is kept forever. A
    #: two-year-old partial capture whose evidence had been pruned would read as
    #: a complete one, and "you held nothing in that bucket" is a false statement
    #: about someone's money, not a missing log line.
    #:
    #: ``none_as_null=True`` is load-bearing, not decoration: a JSONB column
    #: stores Python ``None`` as the JSON value ``null``, which reads back as
    #: ``None`` in Python while being **NOT NULL** in SQL. Without it,
    #: ``WHERE buckets_failed IS NOT NULL`` matches every clean day — the query
    #: this column exists to answer would return the opposite of the truth, and
    #: an ORM-side assertion would never notice. A test pins it.
    buckets_failed: list | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    #: When the capture actually ran (UTC). `max(captured_at)` per user is what
    #: the dashboard's staleness banner is derived from.
    captured_at: datetime = Field(default_factory=utcnow, sa_column=_ts_column())


class SnapshotHolding(SQLModel, table=True):
    """One normalized `portfolio.models.Holding` row, frozen into a snapshot.

    Deliberately a flat copy rather than a foreign key to a positions table:
    a snapshot is a historical record, and a later rename, reclassification or
    delisting must not rewrite what was true on the day.
    """

    __tablename__ = "snapshot_holdings"

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(
        foreign_key="snapshot_days.id",
        ondelete="CASCADE",
        index=True,
    )
    source: str = Field(max_length=64)
    #: Stable within `source`; the other half of M1's identity pair.
    external_id: str = Field(max_length=255)
    asset_type: str = Field(max_length=32)
    symbol: str | None = Field(default=None, max_length=64)
    isin: str | None = Field(default=None, max_length=32)
    units: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(28, 8), nullable=True)
    )
    avg_cost: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(28, 8), nullable=True)
    )
    #: NULL means **unknown cost basis** (M1 §3), never "invested nothing".
    invested_amount: Decimal | None = Field(default=None, sa_column=_money_column(nullable=True))
    current_price: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(28, 8), nullable=True)
    )
    current_value: Decimal = Field(sa_column=_money_column())
    currency: str = Field(default="INR", max_length=8)


class SnapshotRaw(SQLModel, table=True):
    """A source payload exactly as it arrived, kept for forensics.

    One row per source call behind a snapshot: the whole-portfolio call plus one
    per holdings bucket. The call each row came from is recorded **inside**
    `payload` (`kind` / `asset_type`), not in a column, so `source` keeps
    meaning the connector key it means everywhere else in the schema.

    Pruned at 90 days by `services.snapshots.prune_raw`. Normalized rows are
    kept forever — this table is the one that grows without bound.
    """

    __tablename__ = "snapshot_raw"

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(
        foreign_key="snapshot_days.id",
        ondelete="CASCADE",
        index=True,
    )
    source: str = Field(max_length=64)
    payload: dict = Field(sa_column=Column(JSONB, nullable=False))
    #: Indexed because `prune_raw` selects on it, and this is the only table in
    #: the schema expected to reach a size where that matters.
    captured_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


__all__ = [
    "BrokerLink",
    "OAuthPending",
    "SQLModel",
    "SnapshotDay",
    "SnapshotHolding",
    "SnapshotRaw",
    "User",
    "Watchlist",
    "utcnow",
]
