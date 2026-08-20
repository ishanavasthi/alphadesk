"""snapshot_holdings.name — the row's display label, frozen with the row

Card B8. Ranking movers is useless if every line reads `EQUITY:INDS00577`, and
the only place a display name exists today is inside `snapshot_raw.payload`,
which is **pruned at 90 days**. A name kept only there would therefore vanish
from a holding whose history is kept forever.

Nullable, and it stays nullable: rows captured before this migration have no
name and never will (their raw payload may already be gone), and the source
returns an empty label on some rows. A nameless row renders as its
`external_id` — an honest missing name, never a guessed one.

`Text` rather than a bounded string: a name is decoration, and a length
violation must never be able to fail a capture that cannot be retried.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-21

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'snapshot_holdings', sa.Column('name', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('snapshot_holdings', 'name')
