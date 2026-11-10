"""holding exclusions

Adds `holding_exclusions`: source rows the user has told AlphaDesk to leave out
of every figure. The motivating case is #65 — IND Money keeps reporting fixed
deposits at a fraction of their principal (a Rs 10,000 deposit at Rs 171), and
once the user has entered the real deposits by hand (B10) the vendor rows are
both wrong *and* double-counted.

A row here stores the **identity** of a holding — M1's `(source, external_id)`
pair — and nothing about its value. The exclusion is applied at read time to
whatever the source reports now and to every captured day in history, so
excluding or restoring a holding re-prices the whole trend on the next read and
the captured snapshots themselves are never rewritten.

`asset_type` and `name` are frozen copies for display: an excluded row the
source later stops returning still has to be nameable in the "Ignored" list,
or there would be no way to restore it.

`UNIQUE (user_id, source, external_id)` makes excluding idempotent. `user_id`
cascades from `users`, so L1's delete-my-data needs no code of its own.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'holding_exclusions',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('external_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('asset_type', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'source', 'external_id', name='uq_holding_exclusions_user_holding'
        ),
    )
    op.create_index(
        op.f('ix_holding_exclusions_user_id'), 'holding_exclusions', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_holding_exclusions_user_id'), table_name='holding_exclusions')
    op.drop_table('holding_exclusions')
