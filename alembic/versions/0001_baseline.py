"""baseline schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


modality = postgresql.ENUM("strength", "cycling", "mobility", name="modality", create_type=False)
exercise_class = postgresql.ENUM(
    "heavy_compound",
    "bw_compound",
    "db_compound",
    "machine_compound",
    "isolation",
    "corrective",
    name="exercise_class",
    create_type=False,
)
session_type = postgresql.ENUM("lower_core", "upper_pull", "upper_push", "cycling", "other", name="session_type", create_type=False)
local_sensitivity = postgresql.ENUM("none", "mild", "moderate", "severe", name="local_sensitivity", create_type=False)
raw_input_kind = postgresql.ENUM("text", "image", name="raw_input_kind", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    modality.create(bind, checkfirst=True)
    exercise_class.create(bind, checkfirst=True)
    session_type.create(bind, checkfirst=True)
    local_sensitivity.create(bind, checkfirst=True)
    raw_input_kind.create(bind, checkfirst=True)

    op.create_table(
        "exercises",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("modality", modality, nullable=False),
        sa.Column("muscle_groups", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("exercise_class", exercise_class, nullable=True),
        sa.Column("ec_coefficient", sa.Numeric(4, 2), nullable=False),
        sa.Column("peak_e1rm_seed", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_exercises_name", "exercises", ["name"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_type", session_type, nullable=False),
        sa.Column("readiness", sa.Integer(), nullable=True),
        sa.Column("fatigue", sa.Integer(), nullable=True),
        sa.Column("sensitivity", sa.Integer(), nullable=True),
        sa.Column("quality", sa.Integer(), nullable=True),
        sa.Column("time_minutes", sa.Integer(), nullable=True),
        sa.Column("time_benchmark_minutes", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("total_power", sa.Numeric(12, 2), nullable=True),
        sa.Column("index_vs_median", sa.Numeric(8, 2), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("readiness IS NULL OR readiness BETWEEN 1 AND 10", name="ck_sessions_readiness"),
        sa.CheckConstraint("fatigue IS NULL OR fatigue BETWEEN 1 AND 10", name="ck_sessions_fatigue"),
        sa.CheckConstraint("sensitivity IS NULL OR sensitivity BETWEEN 1 AND 10", name="ck_sessions_sensitivity"),
        sa.CheckConstraint("quality IS NULL OR quality BETWEEN 1 AND 10", name="ck_sessions_quality"),
    )
    op.create_index("ix_sessions_started_at", "sessions", ["started_at"])

    op.create_table(
        "strength_sets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exercise_id", sa.BigInteger(), sa.ForeignKey("exercises.id"), nullable=False),
        sa.Column("set_index", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 2), nullable=False),
        sa.Column("rir", sa.Integer(), nullable=True),
        sa.Column("local_sensitivity", local_sensitivity, nullable=False, server_default="none"),
        sa.Column("local_sensitivity_note", sa.Text(), nullable=True),
        sa.Column("is_pr", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("est_1rm", sa.Numeric(8, 2), nullable=True),
        sa.Column("exercise_power", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("rir IS NULL OR rir BETWEEN 0 AND 5", name="ck_strength_sets_rir"),
    )
    op.create_index("ix_strength_sets_exercise_created", "strength_sets", ["exercise_id", "created_at"])

    op.create_table(
        "cycling_efforts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("distance_km", sa.Numeric(6, 2), nullable=True),
        sa.Column("kcal", sa.Integer(), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "raw_inputs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("telegram_msg_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", raw_input_kind, nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("parsed_payload", postgresql.JSONB(), nullable=True),
        sa.Column("claude_model", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "summaries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("summaries")
    op.drop_table("raw_inputs")
    op.drop_table("cycling_efforts")
    op.drop_index("ix_strength_sets_exercise_created", table_name="strength_sets")
    op.drop_table("strength_sets")
    op.drop_index("ix_sessions_started_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_exercises_name", table_name="exercises")
    op.drop_table("exercises")

    bind = op.get_bind()
    raw_input_kind.drop(bind, checkfirst=True)
    local_sensitivity.drop(bind, checkfirst=True)
    session_type.drop(bind, checkfirst=True)
    exercise_class.drop(bind, checkfirst=True)
    modality.drop(bind, checkfirst=True)
