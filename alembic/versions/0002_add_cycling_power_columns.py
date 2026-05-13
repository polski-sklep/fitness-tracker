"""add cycling power columns

Revision ID: 0002_add_cycling_power_columns
Revises: 0001_baseline
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_cycling_power_columns"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cycling_efforts", sa.Column("avg_watts", sa.SmallInteger(), nullable=True))
    op.add_column("cycling_efforts", sa.Column("max_watts", sa.SmallInteger(), nullable=True))
    op.add_column("cycling_efforts", sa.Column("avg_rpm", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("cycling_efforts", "avg_rpm")
    op.drop_column("cycling_efforts", "max_watts")
    op.drop_column("cycling_efforts", "avg_watts")

