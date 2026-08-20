"""manual fixed deposits

Adds `manual_fds` (card B10): the first table in this schema whose rows the
*user* authors rather than the source.

Two facts justify it. IND Money's FD reporting is verified unreliable (B9/#65 —
a Rs 5,000 deposit reported at Rs 162, `total_pnl` frozen for five days, the FD
bucket disappearing from the net-worth total and then from the breakdown), and
an FD is the one holding whose value is **computed, not quoted**: principal,
rate, compounding convention and two dates are the entire instrument. So the
terms are stored and `services.manual_fd` derives the accrued value on every
read — there is no cached valuation column here on purpose, because a stored
number would be wrong the next morning.

`Numeric`, never float: `principal` at (18,2) like every other money column,
`rate_pct` at (9,4) because a bank quoting 7.1875% is ordinary. `compounding`
is a plain string rather than a Postgres enum — adding a convention should be a
code change, not a migration.

**No Fernet.** FD terms are not credentials, and an encrypted column cannot be
summed, filtered or ordered, which is the entire reason this lives in Postgres.

`user_id` is a FK onto `users` with `ON DELETE CASCADE`, so L1's delete-my-data
takes a user's deposits with them inside Postgres and needs no code of its own.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-21

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'manual_fds',
        # uuid4 hex, generated server-side. Surrogate: two deposits at the same
        # bank may share a label, and the id must survive an edit to every
        # other field.
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('label', sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column('principal', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('rate_pct', sa.Numeric(precision=9, scale=4), nullable=False),
        sa.Column('compounding', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('maturity_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # Every read is "this user's deposits" — the list, the holdings merge and
    # the summary block all filter on it and nothing else.
    op.create_index(op.f('ix_manual_fds_user_id'), 'manual_fds', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_manual_fds_user_id'), table_name='manual_fds')
    op.drop_table('manual_fds')
