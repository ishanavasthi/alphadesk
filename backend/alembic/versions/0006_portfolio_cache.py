"""portfolio read-through cache

Adds `portfolio_cache` (issue #15): the cached body of a `/portfolio/*` response,
per user, per cache key. Purely **derived** data — every row can be dropped and
re-read from the source — which is why it is safe to prune it on age, to wipe it
on unlink, and to treat a cache failure as a plain live read.

`UNIQUE (user_id, cache_key)` makes a write an upsert, so a key holds the newest
reading rather than a pile of them. `user_id` is a FK onto `users` with
`ON DELETE CASCADE`, so L1's delete-my-data removes cached holdings inside
Postgres like every other `user_id`-keyed table.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-16

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'portfolio_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('cache_key', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # What the data claims about itself; NULL where the source states none.
        sa.Column('as_of', sa.DateTime(timezone=True), nullable=True),
        # When we read the source. TTLs and the prune are measured against this.
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'cache_key', name='uq_portfolio_cache_user_key'),
    )
    op.create_index(
        op.f('ix_portfolio_cache_user_id'), 'portfolio_cache', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_portfolio_cache_user_id'), table_name='portfolio_cache')
    op.drop_table('portfolio_cache')
