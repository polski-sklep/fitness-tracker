from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.models import Session, StrengthSet
from app.services.exercises import load_seed_peak_e1rm


def mark_prs_for_session(db: DbSession, session_id: int) -> list[str]:
    current_sets = (
        db.query(StrengthSet)
        .join(Session, Session.id == StrengthSet.session_id)
        .filter(StrengthSet.session_id == session_id, Session.deleted_at.is_(None))
        .order_by(StrengthSet.exercise_id, StrengthSet.set_index)
        .all()
    )
    prs: list[str] = []
    seed_peak_e1rm = load_seed_peak_e1rm()

    for strength_set in current_sets:
        strength_set.is_pr = False
        if strength_set.weight_kg is None or float(strength_set.weight_kg) <= 0:
            continue

        prior_best_e1rm = (
            db.query(func.max(StrengthSet.est_1rm))
            .join(Session, Session.id == StrengthSet.session_id)
            .filter(
                StrengthSet.exercise_id == strength_set.exercise_id,
                StrengthSet.weight_kg > 0,
                StrengthSet.id != strength_set.id,
                Session.deleted_at.is_(None),
            )
            .scalar()
        )

        exercise_name = strength_set.exercise.name if strength_set.exercise else ""
        seed_peak = seed_peak_e1rm.get(exercise_name, 0.0)
        baseline = max(float(prior_best_e1rm or 0), seed_peak)
        e1rm_pr = float(strength_set.est_1rm or 0) > baseline
        if e1rm_pr:
            strength_set.is_pr = True
            prs.append(f"{strength_set.exercise.display_name}: {float(strength_set.est_1rm or 0):.1f} kg e1RM")

    return prs
