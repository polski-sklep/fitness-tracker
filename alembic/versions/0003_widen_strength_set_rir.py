"""widen strength set rir constraint

Revision ID: 0003_widen_strength_set_rir
Revises: 0002_add_cycling_power_columns
Create Date: 2026-05-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_widen_strength_set_rir"
down_revision: str | None = "0002_add_cycling_power_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_strength_sets_rir", "strength_sets", type_="check")
    op.create_check_constraint(
        "ck_strength_sets_rir",
        "strength_sets",
        "rir IS NULL OR rir BETWEEN 0 AND 10",
    )


def downgrade() -> None:
    op.drop_constraint("ck_strength_sets_rir", "strength_sets", type_="check")
    op.create_check_constraint(
        "ck_strength_sets_rir",
        "strength_sets",
        "rir IS NULL OR rir BETWEEN 0 AND 5",
    )
