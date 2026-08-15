"""broker link redirect uri

Adds `broker_links.redirect_uri` (nullable varchar): the redirect URI the
dynamically-registered OAuth client on this row was registered against.

Card F3 reuses a user's registered client on re-link rather than minting a new
one every time (C2 §Q5 verified that either is acceptable to the server, and
reusing means one client per user instead of one per login). Dynamic client
registration binds a client to its `redirect_uris`, so a stored client stops
working the moment the callback URL moves — a backend redeploy onto a new
origin, say. Without this column that condition is only discoverable by
watching a user's login fail; with it, `begin_login` re-registers instead.

Nullable with no default: rows written before F3 (there are none in production
— no per-user link has ever been stored) simply read as "unknown redirect",
which makes the next login register a fresh client. That is the safe direction.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "broker_links",
        sa.Column(
            "redirect_uri",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("broker_links", "redirect_uri")
