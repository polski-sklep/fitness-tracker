from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SAEnum

from app.db import Base


class Modality(StrEnum):
    strength = "strength"
    cycling = "cycling"
    mobility = "mobility"


class ExerciseClass(StrEnum):
    heavy_compound = "heavy_compound"
    bw_compound = "bw_compound"
    db_compound = "db_compound"
    machine_compound = "machine_compound"
    isolation = "isolation"
    corrective = "corrective"


class SessionType(StrEnum):
    lower_core = "lower_core"
    upper_pull = "upper_pull"
    upper_push = "upper_push"
    cycling = "cycling"
    other = "other"


class LocalSensitivity(StrEnum):
    none = "none"
    mild = "mild"
    moderate = "moderate"
    severe = "severe"


class RawInputKind(StrEnum):
    text = "text"
    image = "image"


modality_enum = SAEnum(Modality, name="modality", native_enum=True)
exercise_class_enum = SAEnum(ExerciseClass, name="exercise_class", native_enum=True)
session_type_enum = SAEnum(SessionType, name="session_type", native_enum=True)
local_sensitivity_enum = SAEnum(LocalSensitivity, name="local_sensitivity", native_enum=True)
raw_input_kind_enum = SAEnum(RawInputKind, name="raw_input_kind", native_enum=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Exercise(Base, TimestampMixin):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    modality: Mapped[Modality] = mapped_column(modality_enum, nullable=False)
    muscle_groups: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    exercise_class: Mapped[ExerciseClass | None] = mapped_column(exercise_class_enum)
    ec_coefficient: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    peak_e1rm_seed: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)

    sets: Mapped[list["StrengthSet"]] = relationship(back_populates="exercise")


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("readiness IS NULL OR readiness BETWEEN 1 AND 10", name="ck_sessions_readiness"),
        CheckConstraint("fatigue IS NULL OR fatigue BETWEEN 1 AND 10", name="ck_sessions_fatigue"),
        CheckConstraint("sensitivity IS NULL OR sensitivity BETWEEN 1 AND 10", name="ck_sessions_sensitivity"),
        CheckConstraint("quality IS NULL OR quality BETWEEN 1 AND 10", name="ck_sessions_quality"),
        Index("ix_sessions_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    session_type: Mapped[SessionType] = mapped_column(session_type_enum, nullable=False, default=SessionType.other)
    readiness: Mapped[float | None] = mapped_column(Numeric(3, 1))
    fatigue: Mapped[float | None] = mapped_column(Numeric(3, 1))
    sensitivity: Mapped[float | None] = mapped_column(Numeric(3, 1))
    quality: Mapped[float | None] = mapped_column(Numeric(3, 1))
    time_minutes: Mapped[int | None] = mapped_column(Integer)
    time_benchmark_minutes: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    total_power: Mapped[float | None] = mapped_column(Numeric(12, 2))
    index_vs_median: Mapped[float | None] = mapped_column(Numeric(8, 2))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    strength_sets: Mapped[list["StrengthSet"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    cycling_efforts: Mapped[list["CyclingEffort"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    raw_inputs: Mapped[list["RawInput"]] = relationship(back_populates="session")


class StrengthSet(Base, TimestampMixin):
    __tablename__ = "strength_sets"
    __table_args__ = (
        CheckConstraint("rir IS NULL OR rir BETWEEN 0 AND 10", name="ck_strength_sets_rir"),
        Index("ix_strength_sets_exercise_created", "exercise_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"), nullable=False)
    set_index: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    rir: Mapped[int | None] = mapped_column(Integer)
    local_sensitivity: Mapped[LocalSensitivity] = mapped_column(local_sensitivity_enum, nullable=False, default=LocalSensitivity.none)
    local_sensitivity_note: Mapped[str | None] = mapped_column(Text)
    is_pr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    est_1rm: Mapped[float | None] = mapped_column(Numeric(8, 2))
    exercise_power: Mapped[float | None] = mapped_column(Numeric(12, 2))

    session: Mapped[Session] = relationship(back_populates="strength_sets")
    exercise: Mapped[Exercise] = relationship(back_populates="sets")


class CyclingEffort(Base, TimestampMixin):
    __tablename__ = "cycling_efforts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    distance_km: Mapped[float | None] = mapped_column(Numeric(6, 2))
    kcal: Mapped[int | None] = mapped_column(Integer)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    avg_watts: Mapped[int | None] = mapped_column(SmallInteger)
    max_watts: Mapped[int | None] = mapped_column(SmallInteger)
    avg_rpm: Mapped[int | None] = mapped_column(SmallInteger)
    max_rpm: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)

    session: Mapped[Session] = relationship(back_populates="cycling_efforts")


class RawInput(Base, TimestampMixin):
    __tablename__ = "raw_inputs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"))
    telegram_msg_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[RawInputKind] = mapped_column(raw_input_kind_enum, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(Text)
    parsed_payload: Mapped[dict | None] = mapped_column(JSONB)
    claude_model: Mapped[str | None] = mapped_column(Text)

    session: Mapped[Session | None] = relationship(back_populates="raw_inputs")


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
