"""add max rpm to cycling efforts

Revision ID: 0005_add_cycling_max_rpm
Revises: 0004_rfsq_numeric
Create Date: 2026-05-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_cycling_max_rpm"
down_revision: str | None = "0004_rfsq_numeric"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cycling_efforts", sa.Column("max_rpm", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("cycling_efforts", "max_rpm")
