"""store rfsq values as numeric decimals

Revision ID: 0004_rfsq_numeric
Revises: 0003_widen_strength_set_rir
Create Date: 2026-05-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_rfsq_numeric"
down_revision: str | None = "0003_widen_strength_set_rir"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("readiness", "fatigue", "sensitivity", "quality"):
        op.alter_column(
            "sessions",
            column,
            existing_type=sa.Integer(),
            type_=sa.Numeric(3, 1),
            existing_nullable=True,
            postgresql_using=f"{column}::numeric(3,1)",
        )


def downgrade() -> None:
    for column in ("readiness", "fatigue", "sensitivity", "quality"):
        op.alter_column(
            "sessions",
            column,
            existing_type=sa.Numeric(3, 1),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using=f"round({column})::integer",
        )
