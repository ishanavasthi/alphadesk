"""paper watchlist table

Adds `watchlist` (card F4): the one durable piece of Lab state. Lab runs
themselves are ephemeral by decision — held in memory, keyed by user, lost on
restart — but a stock a user approved into their paper watchlist persists.

Each row is a **denormalized decision record** (symbol, company, thesis,
confidence, action, risk_verdict, query) so it stays readable after the run that
produced it is gone. `run_id` is an **opaque, non-FK** column: it references a
run that lives only in memory and may no longer resolve, so "view the original
run" degrades to "no longer available" rather than following a broken join.

`PK (user_id, symbol)` — a stock is on a user's watchlist once. `user_id` is a
FK onto `users` with `ON DELETE CASCADE`, so L1's delete-my-data removes a
user's watchlist inside Postgres like every other `user_id`-keyed table.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-16

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'watchlist',
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('symbol', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('company', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('thesis', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('action', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column('risk_verdict', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column('query', sa.Text(), nullable=True),
        # Opaque, non-FK on purpose: the run it names is in-memory and may be gone.
        sa.Column('run_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'symbol'),
    )


def downgrade() -> None:
    op.drop_table('watchlist')
