from collections import defaultdict
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models import CyclingEffort, Exercise, RawInput, Session, StrengthSet
from app.schemas import ParsedSession
from app.services.exercises import canonicalize, display_name, ec_for_class, load_seed, load_seed_peak_weights
from app.services.power_score import epley_e1rm, exercise_power, index_vs_median, session_power, TIME_BENCHMARKS_MIN
from app.services.pr_detector import mark_prs_for_session
from app.services.session_classifier import classify_session_type


def ensure_exercise(db: DbSession, name: str, exercise_class: str, muscle_groups: list[str]) -> Exercise:
    canonical = canonicalize(name)
    existing = db.query(Exercise).filter(Exercise.name == canonical).first()
    if existing:
        return existing

    _, seed_by_name = load_seed()
    seed = seed_by_name.get(canonical)
    if seed:
        exercise = Exercise(
            name=seed["name"],
            display_name=seed["display_name"],
            modality=seed["modality"],
            muscle_groups=seed["muscle_groups"],
            exercise_class=seed["exercise_class"],
            ec_coefficient=seed["ec_coefficient"],
            peak_e1rm_seed=seed.get("peak_e1rm_seed", 0),
        )
    else:
        exercise = Exercise(
            name=canonical,
            display_name=display_name(canonical),
            modality="strength",
            muscle_groups=muscle_groups,
            exercise_class=exercise_class,
            ec_coefficient=ec_for_class(exercise_class),
            peak_e1rm_seed=0,
        )
    db.add(exercise)
    db.flush()
    return exercise


def create_session_from_payload(db: DbSession, payload: ParsedSession | dict, raw_input_id: int | None = None) -> tuple[Session, list[str]]:
    parsed = payload if isinstance(payload, ParsedSession) else ParsedSession.model_validate(payload)
    exercise_names = [exercise.name for exercise in parsed.exercises]
    session_type = parsed.session_type if parsed.session_type != "other" else classify_session_type(exercise_names)
    benchmark = TIME_BENCHMARKS_MIN.get(session_type)

    session = Session(
        started_at=parsed.started_at or datetime.now(),
        session_type=session_type,
        readiness=parsed.readiness,
        fatigue=parsed.fatigue,
        sensitivity=parsed.sensitivity,
        quality=parsed.quality,
        time_minutes=parsed.time_minutes,
        time_benchmark_minutes=int(benchmark) if benchmark else None,
        notes=parsed.notes,
    )
    db.add(session)
    db.flush()

    exercise_power_values: list[float] = []
    grouped_sets: dict[int, list[dict]] = defaultdict(list)
    first_set_by_exercise: dict[int, StrengthSet] = {}
    seed_peak_weights = load_seed_peak_weights()

    if parsed.modality == "cycling":
        cycling = parsed.cycling
        if cycling:
            db.add(
                CyclingEffort(
                    session_id=session.id,
                    distance_km=cycling.distance_km,
                    kcal=cycling.kcal,
                    duration_min=cycling.duration_min,
                    avg_hr=cycling.avg_hr if cycling.avg_hr else None,
                    avg_watts=cycling.avg_watts,
                    max_watts=cycling.max_watts,
                    avg_rpm=cycling.avg_rpm,
                    max_rpm=cycling.max_rpm,
                    notes=parsed.notes,
                )
            )
    else:
        for parsed_exercise in parsed.exercises:
            exercise = ensure_exercise(
                db,
                parsed_exercise.name,
                parsed_exercise.exercise_class,
                parsed_exercise.muscle_groups,
            )
            for index, parsed_set in enumerate(parsed_exercise.sets, start=1):
                effective_weight_kg = parsed_set.weight_kg if parsed_set.weight_kg is not None else 0.0
                estimated = epley_e1rm(effective_weight_kg, parsed_set.reps)
                strength_set = StrengthSet(
                    session_id=session.id,
                    exercise_id=exercise.id,
                    set_index=index,
                    reps=parsed_set.reps,
                    weight_kg=effective_weight_kg,
                    rir=parsed_set.rir,
                    local_sensitivity=parsed_set.local_sensitivity,
                    local_sensitivity_note=parsed_set.local_sensitivity_note,
                    est_1rm=estimated,
                )
                db.add(strength_set)
                set_payload = parsed_set.model_dump()
                set_payload["weight_kg"] = effective_weight_kg
                grouped_sets[exercise.id].append(set_payload)
                first_set_by_exercise.setdefault(exercise.id, strength_set)

        db.flush()

        for exercise_id, sets in grouped_sets.items():
            exercise = db.get(Exercise, exercise_id)
            prior_peak_weight = (
                db.query(func.max(StrengthSet.weight_kg))
                .join(Session, Session.id == StrengthSet.session_id)
                .filter(
                    StrengthSet.exercise_id == exercise_id,
                    StrengthSet.weight_kg > 0,
                    StrengthSet.session_id != session.id,
                    Session.deleted_at.is_(None),
                )
                .scalar()
            )
            current_peak_weight = max(float(s.get("weight_kg") or 0) for s in sets)
            seed_peak_weight = seed_peak_weights.get(exercise.name, 0.0) if exercise else 0.0
            peak_weight = max(float(prior_peak_weight or 0), seed_peak_weight)
            if peak_weight <= 0:
                peak_weight = current_peak_weight
            score = exercise_power(sets, float(exercise.ec_coefficient), peak_weight, parsed.readiness) if exercise else 0
            first_set_by_exercise[exercise_id].exercise_power = score
            exercise_power_values.append(score)

        total = session_power(
            exercise_power_values,
            parsed.quality,
            parsed.fatigue,
            parsed.sensitivity,
            parsed.time_minutes or int(benchmark or 85),
            benchmark or 85,
        )
        session.total_power = total
        session.index_vs_median = index_vs_median(total, settings.session_median_power)

    if raw_input_id:
        raw_input = db.get(RawInput, raw_input_id)
        if raw_input:
            raw_input.session_id = session.id
            raw_input.parsed_payload = parsed.model_dump(mode="json")

    prs = mark_prs_for_session(db, session.id)
    db.flush()
    return session, prs
