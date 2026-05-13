"""
Recompute derived Power Score, Index, e1RM, and PR fields for all sessions.

Usage:
    python scripts/recompute_all.py
"""
from collections import defaultdict

from sqlalchemy import func

from app.config import settings
from app.db import SessionLocal
from app.models import Exercise, Session, StrengthSet
from app.services.exercises import load_seed_peak_weights
from app.services.power_score import TIME_BENCHMARKS_MIN, epley_e1rm, exercise_power, index_vs_median, session_power
from app.services.pr_detector import mark_prs_for_session


def main() -> None:
    db = SessionLocal()
    try:
        seed_peak_weights = load_seed_peak_weights()
        db.query(StrengthSet).update({StrengthSet.is_pr: False, StrengthSet.exercise_power: None})
        sessions = db.query(Session).filter(Session.deleted_at.is_(None)).order_by(Session.started_at, Session.id).all()

        for session in sessions:
            exercise_scores: list[float] = []
            grouped: dict[int, list[StrengthSet]] = defaultdict(list)
            for strength_set in session.strength_sets:
                strength_set.est_1rm = epley_e1rm(float(strength_set.weight_kg), strength_set.reps)
                grouped[strength_set.exercise_id].append(strength_set)

            for exercise_id, sets in grouped.items():
                exercise = db.get(Exercise, exercise_id)
                payload_sets = [
                    {
                        "reps": item.reps,
                        "weight_kg": float(item.weight_kg),
                        "rir": item.rir,
                        "local_sensitivity": item.local_sensitivity,
                    }
                    for item in sets
                ]
                prior_peak_weight = (
                    db.query(func.max(StrengthSet.weight_kg))
                    .join(Session, Session.id == StrengthSet.session_id)
                    .filter(
                        StrengthSet.exercise_id == exercise_id,
                        StrengthSet.weight_kg > 0,
                        Session.started_at < session.started_at,
                        Session.deleted_at.is_(None),
                    )
                    .scalar()
                )
                current_peak_weight = max(float(item.weight_kg or 0) for item in sets)
                seed_peak_weight = seed_peak_weights.get(exercise.name, 0.0)
                peak_weight = max(float(prior_peak_weight or 0), seed_peak_weight)
                if peak_weight <= 0:
                    peak_weight = current_peak_weight
                score = exercise_power(payload_sets, float(exercise.ec_coefficient), peak_weight, session.readiness)
                sets[0].exercise_power = score
                exercise_scores.append(score)

            benchmark = TIME_BENCHMARKS_MIN.get(session.session_type, 85.0) or 85.0
            session.time_benchmark_minutes = int(benchmark)
            if exercise_scores:
                total = session_power(
                    exercise_scores,
                    session.quality,
                    session.fatigue,
                    session.sensitivity,
                    session.time_minutes or int(benchmark),
                    benchmark,
                )
                session.total_power = total
                session.index_vs_median = index_vs_median(total, settings.session_median_power)

            db.flush()
            mark_prs_for_session(db, session.id)

        db.commit()
        print(f"Recomputed {len(sessions)} sessions")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
