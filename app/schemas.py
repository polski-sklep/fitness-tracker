from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SessionType = Literal["lower_core", "upper_pull", "upper_push", "cycling", "other"]
ExerciseClass = Literal["heavy_compound", "bw_compound", "db_compound", "machine_compound", "isolation", "corrective"]
LocalSensitivity = Literal["none", "mild", "moderate", "severe"]


class ParsedSet(BaseModel):
    reps: int = Field(ge=1)
    weight_kg: float | None = None
    rir: int | None = Field(default=None, ge=0, le=10)
    local_sensitivity: LocalSensitivity = "none"
    local_sensitivity_note: str | None = None


class ParsedExercise(BaseModel):
    name: str
    exercise_class: ExerciseClass
    muscle_groups: list[str] = []
    sets: list[ParsedSet]


class ParsedCycling(BaseModel):
    distance_km: float | None = None
    kcal: int | None = None
    duration_min: int | None = None
    avg_hr: int | None = None
    avg_watts: int | None = None
    max_watts: int | None = None
    avg_rpm: int | None = None
    max_rpm: int | None = None


class ParsedSession(BaseModel):
    modality: Literal["strength", "cycling"]
    started_at: datetime | None = None
    session_type: SessionType = "other"
    readiness: float | None = Field(default=None, ge=1.0, le=10.0)
    fatigue: float | None = Field(default=None, ge=1.0, le=10.0)
    sensitivity: float | None = Field(default=None, ge=1.0, le=10.0)
    quality: float | None = Field(default=None, ge=1.0, le=10.0)
    time_minutes: int | None = None
    notes: str | None = None
    exercises: list[ParsedExercise] = []
    cycling: ParsedCycling | None = None


class RawTextIngest(BaseModel):
    text: str


class PersistSessionRequest(BaseModel):
    parsed: ParsedSession
    raw_input_id: int | None = None


class PersistSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    total_power: float | None
    index_vs_median: float | None
    prs: list[str] = []
