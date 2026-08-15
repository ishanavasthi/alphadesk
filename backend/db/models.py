"""AlphaDesk identity + broker-link tables (card F1).

Three tables only. Portfolio holdings and daily snapshots are deliberately
*not* modelled here — they land in M1/S1, after the C2 data spike tells us what
the IND Money payloads actually look like.

    users          the person. `id` is the Clerk `user_id` (a string, not a
                   UUID) so F2 can adopt Clerk without a key migration.
    broker_links   one row per (user, broker source). Holds the OAuth material
                   needed to keep a link alive: encrypted access/refresh
                   tokens, the dynamically-registered client credentials, and
                   the token endpoint to refresh against.
    oauth_pending  short-lived rows for an in-flight authorization-code flow,
                   keyed by the OAuth `state`. TTL 10 minutes, single use —
                   both enforced in application code (F3), not by the DB.

**Cascade semantics.** `broker_links.user_id` and `oauth_pending.user_id` are
declared `ON DELETE CASCADE` *at the FK level*, so deleting a `users` row wipes
the dependent rows inside Postgres. A later "delete my data" card relies on
that being a schema guarantee rather than an ORM-relationship convention: a
raw `DELETE FROM users` from psql or a migration is just as safe as an ORM
`session.delete(user)`.

Every `*_enc` column is an opaque Fernet token — see `db.crypto`. Never select
one into a log line.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
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


__all__ = ["BrokerLink", "OAuthPending", "SQLModel", "User", "utcnow"]
